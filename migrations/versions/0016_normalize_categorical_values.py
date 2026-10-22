"""Normalize categorical values: case_type, victim gender, victim race.

Revision ID: 0016
Revises: 0015

Background
----------
A normalization audit (2026-05-30) found the same inconsistency recurring
across three filterable dimensions, because per-adapter write paths applied
different conventions (and the shared ``normalize_gender`` was wired into only
6 of ~10 adapters):

- ``cold_case.cases.case_type``: 'missing-person' (70) AND 'missing_person'
  (35); 'unidentified-person' (23). Canonical = lowercase snake_case.
- ``cold_case.victim.gender``: 'M'/'F' AND 'male'/'female'. Canonical = M/F.
  ('unknown' is left as-is — a recorded value distinct from NULL.)
- ``cold_case.victim.race``: pure case variants ('black'/'Black'/'BLACK',
  'white'/'WHITE', 'asian'/'ASIAN', 'hispanic', 'unknown'). Canonical =
  Title-case for single-token values. Multi-word / punctuated values
  ('Black or African American', 'White/Caucasian', ...) are LEFT UNCHANGED —
  merging those synonyms is a sensitive reclassification of source race data,
  deliberately out of scope.

The rules are inlined here (not imported from
``etl.services.normalizers``) so the migration is deterministic regardless of
future edits to that module. The module gains matching ``normalize_case_type``
/ ``normalize_race`` helpers so re-ingests stay consistent.

Reversibility
-------------
Casing/spelling is collapsed; the pre-normalization variants are not recorded,
so downgrade is a no-op.
"""

from __future__ import annotations

import logging
import re

from alembic import op
from sqlalchemy import text

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_logger = logging.getLogger("alembic.runtime.migration")


def _norm_case_type(v: str) -> str:
    out = re.sub(r"[\s-]+", "_", v.strip().lower())
    return re.sub(r"_+", "_", out).strip("_")


def _norm_race(v: str) -> str:
    s = " ".join(v.split())
    if not s:
        return s
    if len(s.split()) > 1 or "/" in s or "\\" in s:
        return s
    return s[:1].upper() + s[1:].lower()


def _norm_gender(v: str) -> str | None:
    """male/female/m/f → M/F; anything else (incl. 'unknown') left untouched."""
    low = v.strip().lower()
    if low in ("m", "male"):
        return "M"
    if low in ("f", "female"):
        return "F"
    return None


def _apply(bind, table: str, column: str, fn) -> int:  # type: ignore[no-untyped-def]
    """Re-map distinct column values via fn; UPDATE only where it changes."""
    changed = 0
    rows = bind.execute(
        text(f"SELECT DISTINCT {column} AS v FROM {table} WHERE {column} IS NOT NULL")
    ).all()
    for (val,) in rows:
        norm = fn(val)
        if norm is not None and norm != val:
            res = bind.execute(
                text(f"UPDATE {table} SET {column} = :n WHERE {column} = :o"),
                {"n": norm, "o": val},
            )
            _logger.info("0016: %s.%s %r -> %r (%d rows)", table, column, val, norm, res.rowcount)
            changed += res.rowcount
    return changed


def upgrade() -> None:
    bind = op.get_bind()
    n = _apply(bind, "cold_case.cases", "case_type", _norm_case_type)
    _logger.info("0016: normalized %d case_type rows", n)
    n = _apply(bind, "cold_case.victim", "gender", _norm_gender)
    _logger.info("0016: normalized %d gender rows", n)
    n = _apply(bind, "cold_case.victim", "race", _norm_race)
    _logger.info("0016: normalized %d race rows", n)


def downgrade() -> None:
    _logger.warning(
        "0016 downgrade: pre-normalization variants were not recorded; no-op."
    )
