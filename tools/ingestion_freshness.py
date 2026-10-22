"""Report how recently each source was (re-)ingested, and flag stale ones.

Source sites change format and adapters can break silently, leaving a source's
data quietly stale. This read-only check surfaces, per source system, the most
recent published dataset version and its age, and exits non-zero if any source
is older than the threshold so it can drive a cron alarm.

Run as a module from the repo root:

  APP_ENV=dev DATABASE_URL=postgresql+psycopg2://casesignal:casesignal@localhost:5433/casesignal \
    python -m tools.ingestion_freshness --stale-days 60

Application package lives under ``src/``; ``_ensure_src_on_path`` adds it so the
command works from a fresh checkout (mirrors tools/audit_cold_case.py).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SourceFreshness:
    source_code: str
    last_ingest: datetime | None
    published_cases: int


def age_days(last: datetime | None, now: datetime) -> int | None:
    """Whole days between ``last`` and ``now``; None when undated."""
    if last is None:
        return None
    return max(0, (now - last).days)


def build_report(
    rows: list[SourceFreshness], *, stale_days: int, now: datetime
) -> tuple[str, bool]:
    """Render the freshness table and return (text, any_stale).

    Pure (no DB / no clock) so it is unit-testable. Rows are sorted oldest-first
    so the most-stale sources lead. A source with no published version, or one
    older than ``stale_days``, counts as stale.
    """

    def sort_key(r: SourceFreshness) -> tuple[int, float]:
        a = age_days(r.last_ingest, now)
        # Undated sources sort first (most urgent); then oldest-to-newest.
        return (0, 0.0) if a is None else (1, -a)

    ordered = sorted(rows, key=sort_key)
    any_stale = False
    lines = [
        f"{'SOURCE':<22} {'LAST INGEST':<12} {'AGE':>6}  {'CASES':>6}  STATUS",
        "-" * 60,
    ]
    for r in ordered:
        a = age_days(r.last_ingest, now)
        stale = a is None or a > stale_days
        any_stale = any_stale or stale
        when = r.last_ingest.date().isoformat() if r.last_ingest else "never"
        age = "n/a" if a is None else f"{a}d"
        status = "STALE" if stale else "ok"
        lines.append(
            f"{r.source_code:<22} {when:<12} {age:>6}  {r.published_cases:>6}  {status}"
        )
    stale_count = sum(
        1
        for r in ordered
        if (age_days(r.last_ingest, now) is None)
        or (age_days(r.last_ingest, now) or 0) > stale_days
    )
    lines.append("-" * 60)
    lines.append(
        f"{len(ordered)} sources; {stale_count} stale (> {stale_days}d). "
        + ("ACTION NEEDED" if any_stale else "all fresh")
    )
    return "\n".join(lines), any_stale


# Join EVERY dataset_version (any status) so a source that has attempted an
# ingest but has no PUBLISHED version yet (e.g. a first ingest that failed before
# publish) is still reported — MAX(...) FILTER yields NULL last_ingest, which
# build_report renders as "never" and counts as stale. Filtering 'published' in
# the JOIN instead would drop those rows entirely and let the monitor pass them
# silently (Codex P2). A bare source_system with no dataset_version at all is a
# registration with no ingest attempt, not a freshness signal, so it's excluded.
_QUERY = """
SELECT ss.source_code AS source_code,
       MAX(dv.created_at) FILTER (WHERE dv.ingestion_status = 'published') AS last_ingest,
       (
         SELECT COUNT(*)
           FROM cold_case.cases c
           JOIN etl.dataset_version d2
             ON d2.dataset_version_id = c.dataset_version_id
          WHERE d2.source_system_id = ss.source_system_id
            AND d2.ingestion_status = 'published'
       ) AS published_cases
  FROM etl.source_system ss
  JOIN etl.dataset_version dv
    ON dv.source_system_id = ss.source_system_id
 GROUP BY ss.source_code, ss.source_system_id
"""


def main(argv: list[str] | None = None) -> int:
    _ensure_src_on_path()

    from sqlalchemy import text

    from casesignal.etl.config import settings
    from casesignal.etl.services.db import create_db_engine, create_session_factory

    parser = argparse.ArgumentParser(
        description="Report per-source ingestion freshness; exit 1 if any source is stale."
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=60,
        help="Flag sources whose latest published ingest is older than this (default 60).",
    )
    args = parser.parse_args(argv)

    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = [
            SourceFreshness(
                source_code=r.source_code,
                last_ingest=r.last_ingest,
                published_cases=int(r.published_cases),
            )
            for r in session.execute(text(_QUERY)).all()
        ]

    report, any_stale = build_report(
        rows, stale_days=args.stale_days, now=datetime.now(timezone.utc)
    )
    print(report)
    return 1 if any_stale else 0


def _ensure_src_on_path() -> None:
    src = Path(__file__).resolve().parent.parent / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


if __name__ == "__main__":
    raise SystemExit(main())
