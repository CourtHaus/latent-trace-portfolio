"""Raw load stage for cold case Wyoming DCI ingestion.

Reads the unified Wyoming CSV and inserts rows into a per-dataset-version
raw table (raw_cold_case.cold_case_wy_dci_dv<N>). Column list is driven
by COLD_CASE_WY_DCI_EXPECTED_COLUMNS so adding a new column in a future
extract is a single-location change.

All 15 WY column names are valid SQL identifiers — no quoting required
(contrast with VA's hyphenated 'incident-date' etc).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from casesignal.etl.adapters.cold_case_wy_dci.schema_baseline import (
    COLD_CASE_WY_DCI_EXPECTED_COLUMNS,
)
from casesignal.etl.services.pipeline_context import PipelineContext

# Single source of truth for raw table columns. 1:1 csv_name → sql_name.
# Ordered list so insert / table-create stay aligned.
RAW_COLUMNS: list[str] = [
    "source_case_id",
    "reported_date",
    "crime_types",
    "weapon",
    "victim_name",
    "victim_age",
    "victim_sex",
    "victim_race",
    "scene_type",
    "scene_address",
    "scene_business_name",
    "scene_city",
    "scene_county",
    "synopsis",
    "photo_filename",
]

# Defensive guard: keep RAW_COLUMNS in lockstep with the schema baseline.
assert set(RAW_COLUMNS) == set(
    COLD_CASE_WY_DCI_EXPECTED_COLUMNS
), "RAW_COLUMNS drifted from COLD_CASE_WY_DCI_EXPECTED_COLUMNS"

# Validation thresholds — see Phase 6 Task C spec.
#
# _MIN_SYNOPSIS_LEN lowered from 100 → 50 in Task D after the smoke test on
# the real 32-row extract showed 5 legitimate-but-terse rows under 100 chars
# (e.g. "Two German Nationals shot in desert near Wamsutter, WY."). 50 still
# catches truly empty / single-word corruption while not rejecting real
# narrative content.
_MIN_ROWS = 25
_MIN_SYNOPSIS_LEN = 50


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cold_case_wy_dci_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    """Build CREATE TABLE from RAW_COLUMNS. All TEXT; parsing happens in transform."""
    column_defs = ",\n        ".join(f"{name} TEXT" for name in RAW_COLUMNS)
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id INT NOT NULL,
        {column_defs}
    )
    """


def _insert_row_sql(table_ident: str) -> str:
    """Build INSERT statement from RAW_COLUMNS."""
    sql_cols = ["dataset_version_id"] + RAW_COLUMNS
    placeholders = [":dataset_version_id"] + [f":c{i}" for i in range(len(RAW_COLUMNS))]
    return (
        f"INSERT INTO {table_ident} ({', '.join(sql_cols)}) " f"VALUES ({', '.join(placeholders)})"
    )


def _row_to_params(row: dict[str, Any], dataset_version_id: int) -> dict[str, Any]:
    """Map a CSV row dict to the INSERT params dict, keyed by c0..cN."""
    params: dict[str, Any] = {"dataset_version_id": dataset_version_id}
    for i, csv_name in enumerate(RAW_COLUMNS):
        value = row.get(csv_name)
        # Normalize empty-string to None so transform's NULL handling is uniform.
        if isinstance(value, str) and value == "":
            value = None
        params[f"c{i}"] = value
    return params


def load_cold_case_raw(context: PipelineContext) -> None:
    logger = context.logger
    if logger is None:
        raise RuntimeError("PipelineContext.logger must be set before running stages.")

    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set (run register_source first).")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError(
            "session_factory in pipeline context metadata is not a SQLAlchemy sessionmaker."
        )

    csv_path: Path = context.source_path
    table_ident = _raw_table_name(context.dataset_version_id)

    rows_inserted = 0
    short_synopsis_rows: list[str] = []

    with session_factory() as session:
        try:
            # Lazy create the raw table for this dataset version.
            session.execute(text(_create_raw_table_sql(table_ident)))
            # Clear any pre-existing rows (re-run safety).
            session.execute(
                text(f"DELETE FROM {table_ident} WHERE dataset_version_id = :dv"),
                {"dv": context.dataset_version_id},
            )
            session.commit()

            # utf-8-sig strips any leading BOM defensively.
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                header = set(reader.fieldnames or [])
                missing = COLD_CASE_WY_DCI_EXPECTED_COLUMNS - header
                if missing:
                    raise ValueError(f"CSV missing expected columns: {sorted(missing)}")

                insert_sql = text(_insert_row_sql(table_ident))
                batch: list[dict[str, Any]] = []
                for row in reader:
                    synopsis = (row.get("synopsis") or "").strip()
                    if len(synopsis) < _MIN_SYNOPSIS_LEN:
                        short_synopsis_rows.append(
                            row.get("source_case_id") or "(missing source_case_id)"
                        )
                    batch.append(_row_to_params(row, context.dataset_version_id))

                if batch:
                    session.execute(insert_sql, batch)
                session.commit()
                rows_inserted = len(batch)

            session.execute(text(f"ANALYZE {table_ident}"))
            session.commit()

        except Exception:
            session.rollback()
            raise

    context.increment_row_count("raw_load", rows_inserted)

    # Validation: row-count floor.
    if rows_inserted < _MIN_ROWS:
        raise RuntimeError(
            f"WY raw_load: inserted only {rows_inserted} rows (< floor {_MIN_ROWS}); "
            f"refusing to proceed."
        )

    # Validation: synopsis length floor.
    if short_synopsis_rows:
        raise RuntimeError(
            f"WY raw_load: {len(short_synopsis_rows)} row(s) have synopsis "
            f"shorter than {_MIN_SYNOPSIS_LEN} chars: "
            f"{short_synopsis_rows[:5]}"
            + (f" (+{len(short_synopsis_rows) - 5} more)" if len(short_synopsis_rows) > 5 else "")
        )

    logger.info(
        "Cold case WY DCI raw load: %d rows -> %s",
        rows_inserted,
        table_ident,
    )
