"""Raw load stage for cold case VA ingestion.

Reads the CSV and inserts rows into a per-dataset-version raw table
(raw_cold_case.cases_dv<N>). Column list is driven by RAW_COLUMNS so adding
a new column in a future extract is a single-location change.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from casesignal.etl.adapters.cold_case_va.schema_baseline import COLD_CASE_VA_EXPECTED_COLUMNS
from casesignal.etl.services.pipeline_context import PipelineContext

# Single source of truth for raw table columns.
# Each entry: (csv_column_name, sql_column_name)
# sql_column_name is already double-quoted when it contains hyphens so
# _create_raw_table_sql and _insert_row_sql can splice directly.
RAW_COLUMNS: list[tuple[str, str]] = [
    ("_id", "_id"),
    ("case_name", "case_name"),
    ("post_id", "post_id"),
    ("type", "type"),
    ("incident-date", '"incident-date"'),
    ("address", "address"),
    ("city", "city"),
    ("state", "state"),
    ("vspccd-number", '"vspccd-number"'),
    ("about", "about"),
    ("victim-fields_first-name", '"victim-fields_first-name"'),
    ("victim-fields_last-name", '"victim-fields_last-name"'),
    ("victim-fields_gender", '"victim-fields_gender"'),
    ("victim-fields_height", '"victim-fields_height"'),
    ("victim-fields_weight", '"victim-fields_weight"'),
    ("victim-fields_age", '"victim-fields_age"'),
    ("victim-fields_race", '"victim-fields_race"'),
    ("victim-fields_eye-color", '"victim-fields_eye-color"'),
    ("victim-fields_hair-color", '"victim-fields_hair-color"'),
    ("contact-first-name", '"contact-first-name"'),
    ("contact-last-name", '"contact-last-name"'),
    ("contact-phone-number", '"contact-phone-number"'),
    ("contact-address", '"contact-address"'),
    ("contact-email", '"contact-email"'),
    ("geographic-location", '"geographic-location"'),
]


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.cases_dv{dataset_version_id}"


def _create_raw_table_sql(table_ident: str) -> str:
    """Build CREATE TABLE from RAW_COLUMNS. All text; parsing happens in transform."""
    column_defs = ",\n        ".join(f"{sql_name} TEXT" for _, sql_name in RAW_COLUMNS)
    return f"""
    CREATE TABLE IF NOT EXISTS {table_ident} (
        dataset_version_id INT NOT NULL,
        {column_defs}
    )
    """


def _insert_row_sql(table_ident: str) -> str:
    """Build INSERT statement from RAW_COLUMNS."""
    sql_cols = ["dataset_version_id"] + [sql_name for _, sql_name in RAW_COLUMNS]
    placeholders = [":dataset_version_id"] + [f":c{i}" for i in range(len(RAW_COLUMNS))]
    return f"INSERT INTO {table_ident} ({', '.join(sql_cols)}) VALUES ({', '.join(placeholders)})"


def _row_to_params(row: dict[str, Any], dataset_version_id: int) -> dict[str, Any]:
    """Map a CSV row dict to the INSERT params dict[str, Any], keyed by c0..cN."""
    params: dict[str, Any] = {"dataset_version_id": dataset_version_id}
    for i, (csv_name, _) in enumerate(RAW_COLUMNS):
        params[f"c{i}"] = row.get(csv_name)
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
    with session_factory() as session:
        try:
            # Create the raw table for this dataset version
            session.execute(text(_create_raw_table_sql(table_ident)))
            # Clear any pre-existing rows (re-run safety)
            session.execute(
                text(f"DELETE FROM {table_ident} WHERE dataset_version_id = :dv"),
                {"dv": context.dataset_version_id},
            )
            session.commit()

            # utf-8-sig strips the leading BOM so "_id" matches cleanly.
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                header = set(reader.fieldnames or [])
                missing = COLD_CASE_VA_EXPECTED_COLUMNS - header
                if missing:
                    raise ValueError(f"CSV missing expected columns: {sorted(missing)}")

                insert_sql = text(_insert_row_sql(table_ident))
                batch = [_row_to_params(row, context.dataset_version_id) for row in reader]
                session.execute(insert_sql, batch)
                session.commit()
                rows_inserted = len(batch)

            session.execute(text(f"ANALYZE {table_ident}"))
            session.commit()

        except Exception:
            session.rollback()
            raise

    context.increment_row_count("raw_load", rows_inserted)
    logger.info(
        "Cold case VA raw load: %d rows -> %s",
        rows_inserted,
        table_ident,
    )

    # Absorbed from former validate_raw stage — assertions on raw rows.
    from casesignal.etl.adapters.cold_case_va.validation import validate_cold_case_raw

    validate_cold_case_raw(context)
