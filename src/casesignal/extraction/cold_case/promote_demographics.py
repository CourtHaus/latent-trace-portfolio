"""Phase-2 demographics promotion: fill NULL victim age/gender from the
per-victim Tier-2 roster (cold_case.victim_extraction).

Spec: docs/engineering-decisions.md §4.
This retires the global no-promote rule for victim demographics — safe now
because values are victim-identity-bound via victim_extraction.victim_id
(set by reconciliation), not case-level scalars.

Hard invariants:
  - Fill NULL only. A non-NULL victim value (including gender='unknown') is
    source-provided and is never overwritten.
  - Only non-low-confidence extraction fields are promoted (these always
    carry resolved source offsets, so the reveal-source UI works).
  - Gender is promoted only when 'M' or 'F' (defense in depth; the extractor
    already enforces this vocabulary).
  - Promoted columns are tagged age_source/gender_source = 'tier2'.

Also exposes the corpus-backfill CLI (casesignal-promote-victim-demographics).
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import create_engine, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class PromotionCounts:
    ages_filled: int
    genders_filled: int


# Latest linked extraction row per victim. The corpus currently has exactly
# one prompt_hash and no victim with >1 row (verified 2026-06-12), but
# DISTINCT ON keeps this correct across future prompt revisions.
_LATEST_LINKED = """
    SELECT DISTINCT ON (victim_id)
           victim_id,
           victim_age_text, victim_age_low_confidence,
           victim_gender_text, victim_gender_low_confidence
      FROM cold_case.victim_extraction
     WHERE victim_id IS NOT NULL
       AND prompt_tier = 2
     ORDER BY victim_id, extracted_at DESC, id DESC
"""


def promote_victim_demographics(
    session: Session,
    *,
    case_id: int | None = None,
) -> PromotionCounts:
    """Fill NULL victim.age_text / victim.gender from the linked roster.

    ``case_id=None`` promotes corpus-wide (the backfill); a concrete case_id
    scopes to one case (the per-extraction worker/CLI path). Caller controls
    commit. Returns the number of rows filled per field.
    """
    case_filter = "AND v.case_id = :cid" if case_id is not None else ""
    params: dict[str, object] = {}
    if case_id is not None:
        params["cid"] = case_id

    age_result = cast(
        CursorResult[Any],
        session.execute(
            text(f"""
                UPDATE cold_case.victim v
                   SET age_text = ve.victim_age_text,
                       age_source = 'tier2'
                  FROM ({_LATEST_LINKED}) ve
                 WHERE v.victim_id = ve.victim_id
                   AND v.age_text IS NULL
                   AND ve.victim_age_text IS NOT NULL
                   AND NOT ve.victim_age_low_confidence
                   {case_filter}
            """),
            params,
        ),
    )

    gender_result = cast(
        CursorResult[Any],
        session.execute(
            text(f"""
                UPDATE cold_case.victim v
                   SET gender = ve.victim_gender_text,
                       gender_source = 'tier2'
                  FROM ({_LATEST_LINKED}) ve
                 WHERE v.victim_id = ve.victim_id
                   AND v.gender IS NULL
                   AND ve.victim_gender_text IN ('M', 'F')
                   AND NOT ve.victim_gender_low_confidence
                   {case_filter}
            """),
            params,
        ),
    )

    return PromotionCounts(
        ages_filled=age_result.rowcount,
        genders_filled=gender_result.rowcount,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="casesignal-promote-victim-demographics",
        description="Promote per-victim Tier-2 age/gender onto NULL"
        " cold_case.victim columns (fill-NULL-only; tags *_source='tier2').",
    )
    parser.add_argument(
        "--case-id", type=int, default=None, help="Promote a single case only"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the promotion in a transaction and ROLL BACK; print counts",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    engine = create_engine(os.environ["DATABASE_URL"])
    session_factory = sessionmaker(engine)
    with session_factory() as session:
        counts = promote_victim_demographics(session, case_id=args.case_id)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    engine.dispose()
    mode = "[dry-run, rolled back] " if args.dry_run else ""
    print(
        f"{mode}Promoted {counts.ages_filled} ages and"
        f" {counts.genders_filled} genders onto cold_case.victim."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
