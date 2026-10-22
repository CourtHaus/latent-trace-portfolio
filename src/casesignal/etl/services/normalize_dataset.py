"""Shared pipeline stage: canonicalize categorical values for a freshly
transformed dataset_version.

Lifted OUT of the per-adapter transforms into the shared runner so it always
runs and can't be forgotten — the failure mode that left ``normalize_gender``
wired into only 6 of ~10 adapters. Single logic source: the pure functions in
``etl.services.normalizers``. Idempotent: re-running changes nothing.

Scope is the just-written dataset_version's rows only (cheap; touches the new
ingest, not the whole corpus). The one-time corpus backfill lives in migration
0016.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.services.normalizers import (
    normalize_case_type,
    normalize_gender,
    normalize_race,
)
from casesignal.etl.services.pipeline_context import PipelineContext


def _remap(
    session: Session,
    table: str,
    column: str,
    where: str,
    params: dict[str, Any],
    fn: Callable[[str | None], str | None],
) -> int:
    """Re-map a column's distinct values via ``fn``, UPDATE only where changed.

    ``table``/``column``/``where`` are code literals (never user input); the
    only bound values are the params + the normalized/original values.
    """
    rows = session.execute(
        text(  # noqa: S608 - identifiers are literals, values are bound
            f"SELECT DISTINCT {column} AS v FROM {table}"
            f" WHERE {where} AND {column} IS NOT NULL"
        ),
        params,
    ).all()
    changed = 0
    for (val,) in rows:
        norm = fn(val)
        if norm is not None and norm != val:
            res = session.execute(
                text(  # noqa: S608 - identifiers are literals, values are bound
                    f"UPDATE {table} SET {column} = :__n WHERE {where} AND {column} = :__o"
                ),
                {**params, "__n": norm, "__o": val},
            )
            # Session.execute is typed Result; UPDATE returns a CursorResult.
            changed += res.rowcount  # type: ignore[attr-defined]
    return changed


def normalize_dataset_values(session: Session, dataset_version_id: int) -> int:
    """Canonicalize case_type + victim gender + victim race for one dataset.

    Returns the number of rows changed. Caller commits. Gender 'unknown' is
    preserved (``normalize_gender`` returns None for it → the remap skips it).
    """
    params = {"dv": dataset_version_id}
    victim_scope = "case_id IN (SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
    changed = _remap(
        session, "cold_case.cases", "case_type", "dataset_version_id = :dv", params, normalize_case_type
    )
    changed += _remap(session, "cold_case.victim", "gender", victim_scope, params, normalize_gender)
    changed += _remap(session, "cold_case.victim", "race", victim_scope, params, normalize_race)
    return changed


def normalize_dataset_stage(context: PipelineContext) -> None:
    """Runner stage: open a session and normalize the dataset's categoricals."""
    dataset_version_id = context.require_dataset_version_id()
    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")
    with session_factory() as session:
        changed = normalize_dataset_values(session, dataset_version_id)
        session.commit()
    if context.logger is not None:
        context.logger.info("normalize: canonicalized %d categorical value(s).", changed)
