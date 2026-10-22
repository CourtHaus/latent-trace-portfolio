"""Re-run transform → normalize → publish for an EXISTING dataset_version
against its already-loaded raw table — no re-scrape, no re-fetch.

Motivation: a dataset_version can fail in the ``transform`` stage (e.g. a
``source_case_id`` collision the adapter later learned to disambiguate) AFTER
``load_raw`` already persisted every source row to
``raw_cold_case.<adapter>_dv<N>``. When the adapter has since been fixed, the
correct repair is to rebuild ``cold_case.cases`` from the intact raw rows with
the current adapter code and publish — not to re-scrape the source.

The standard runner (``run_pipeline``) only executes the full stage sequence
starting at ``prepare_input``/``load_raw``; there is no flag to resume at
``transform``. This runner fills that gap for a single known dataset_version.

What it does, in order:
  1. Resolve the source + adapter, attach the DB.
  2. Safety-check: the dvid belongs to the named source, its
     ingestion_status is 'failed' (only failed ingests are rebuildable —
     never delete a published/archived dataset's live enrichments), and the
     raw table for this dvid exists and has rows.
  3. Delete the partial ``cold_case.cases`` rows for the dvid (ON DELETE
     CASCADE clears victims/photos/contacts/extractions/jobs).
  4. Open a fresh ``ingestion_run`` and run transform → normalize → publish.

Tier-1 extraction and geocoding are only *enqueued* by transform, so this
finishes in seconds-to-minutes regardless of corpus size; the LLM/geocoding
work backfills asynchronously afterward.

    uv run python -m casesignal.etl.runners.republish_from_raw \\
        --source-key cold_case_ut_2026_05_11 --dataset-version-id 363 [--dry-run] [--yes]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from casesignal.etl.runners.run_pipeline import (
    DEFAULT_CATALOG_PATH,
    attach_database,
    build_adapter_registry,
    build_pipeline_context,
    cleanup_context,
    configure_logging,
    resolve_source_definition,
)
from casesignal.etl.services.ingestion_tracking import mark_ingestion_run_failed
from casesignal.etl.services.normalize_dataset import normalize_dataset_stage
from casesignal.etl.services.pipeline_context import PipelineContext


def _require_session_factory(context: PipelineContext) -> sessionmaker[Session]:
    sf = context.get_metadata("session_factory")
    if not isinstance(sf, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")
    return sf


def _find_raw_table(session_factory: sessionmaker[Session], dvid: int) -> str | None:
    """Return the single raw_cold_case table whose name ends in `_dv<dvid>`."""
    with session_factory() as session:
        rows = session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'raw_cold_case' "
                "AND table_name ~ ('_dv' || :dvid || '$')"
            ),
            {"dvid": str(dvid)},
        ).all()
    if len(rows) == 1:
        return str(rows[0].table_name)
    return None


def _dataset_version_meta(
    session_factory: sessionmaker[Session], dvid: int
) -> tuple[str, str] | None:
    """Return (source_code, ingestion_status) for this dataset_version, or None."""
    with session_factory() as session:
        row = session.execute(
            text(
                "SELECT ss.source_code, dv.ingestion_status "
                "FROM etl.dataset_version dv "
                "JOIN etl.source_system ss ON ss.source_system_id = dv.source_system_id "
                "WHERE dv.dataset_version_id = :dvid"
            ),
            {"dvid": dvid},
        ).first()
    return (str(row.source_code), str(row.ingestion_status)) if row is not None else None


def _count(session_factory: sessionmaker[Session], sql: str, dvid: int) -> int:
    with session_factory() as session:
        return int(session.execute(text(sql), {"dvid": dvid}).scalar_one())


def _delete_partial_cases(session_factory: sessionmaker[Session], dvid: int) -> int:
    with session_factory() as session:
        result = session.execute(
            text("DELETE FROM cold_case.cases WHERE dataset_version_id = :dvid"),
            {"dvid": dvid},
        )
        session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


def _open_ingestion_run(session_factory: sessionmaker[Session], dvid: int) -> int:
    with session_factory() as session:
        run_id = session.execute(
            text(
                "INSERT INTO etl.ingestion_run (dataset_version_id, run_status, notes) "
                "VALUES (:dvid, 'running', 'republish_from_raw: re-transform existing raw') "
                "RETURNING ingestion_run_id"
            ),
            {"dvid": dvid},
        ).scalar_one()
        session.commit()
        return int(run_id)


def republish(
    source_key: str,
    dataset_version_id: int,
    catalog_path: Path,
    *,
    dry_run: bool,
    assume_yes: bool,
    logger: logging.Logger | None = None,
) -> int:
    logger = logger or configure_logging()
    source_definition = resolve_source_definition(source_key=source_key, catalog_path=catalog_path)
    context = build_pipeline_context(source_definition=source_definition, logger=logger)
    registry = build_adapter_registry()
    adapter = registry.create_adapter(source_definition)

    try:
        attach_database(context)
        sf = _require_session_factory(context)

        # --- Safety checks (BEFORE any destructive action) ---
        meta = _dataset_version_meta(sf, dataset_version_id)
        if meta is None:
            logger.error("dataset_version_id=%s does not exist.", dataset_version_id)
            return 2
        owner_code, status = meta
        if owner_code != source_definition.source_code:
            logger.error(
                "dataset_version_id=%s belongs to source_code=%r, not %r (source-key %r). "
                "Refusing to operate on a mismatched dataset.",
                dataset_version_id,
                owner_code,
                source_definition.source_code,
                source_key,
            )
            return 2
        # This runner RECOVERS failed ingests. Rebuilding a published/archived/
        # draft version would delete its live cases + enrichments (photos,
        # extractions, geocoding) and only re-enqueue the jobs — so a typo'd
        # dvid must not reach the destructive path. Only 'failed' is rebuildable.
        if status != "failed":
            logger.error(
                "dataset_version_id=%s has ingestion_status=%r, not 'failed'. "
                "This runner only rebuilds FAILED versions; refusing to delete a "
                "%s dataset's existing cases/enrichments.",
                dataset_version_id,
                status,
                status,
            )
            return 2

        raw_table = _find_raw_table(sf, dataset_version_id)
        if raw_table is None:
            logger.error(
                "No single raw_cold_case table ending in _dv%s — cannot re-transform "
                "without intact raw rows.",
                dataset_version_id,
            )
            return 2
        raw_rows = _count(
            sf, f"SELECT COUNT(*) FROM raw_cold_case.{raw_table} WHERE dataset_version_id = :dvid", dataset_version_id
        )
        partial_cases = _count(
            sf, "SELECT COUNT(*) FROM cold_case.cases WHERE dataset_version_id = :dvid", dataset_version_id
        )

        logger.info(
            "Republish plan for dataset_version_id=%s (source %s):\n"
            "  raw table         : raw_cold_case.%s (%d rows)\n"
            "  partial cases now : %d  (will be DELETED, cascades to victims/photos/jobs)\n"
            "  action            : transform -> normalize -> publish from raw",
            dataset_version_id,
            source_key,
            raw_table,
            raw_rows,
            partial_cases,
        )

        if raw_rows == 0:
            logger.error("Raw table has 0 rows for this dvid — nothing to re-transform.")
            return 2

        if dry_run:
            logger.info("--dry-run: no changes made.")
            return 0

        if not assume_yes:
            logger.error("Refusing to mutate without --yes (or use --dry-run).")
            return 2

        # --- Destructive path ---
        deleted = _delete_partial_cases(sf, dataset_version_id)
        logger.info("Deleted %d partial case rows for dataset_version_id=%s.", deleted, dataset_version_id)

        context.dataset_version_id = dataset_version_id
        context.ingestion_run_id = _open_ingestion_run(sf, dataset_version_id)
        logger.info("Opened ingestion_run_id=%s.", context.ingestion_run_id)

        try:
            adapter.run_stage(context, "transform", adapter.transform)
            adapter.run_stage(context, "normalize", normalize_dataset_stage)
            adapter.run_stage(context, "publish", adapter.publish)
        except Exception as exc:  # noqa: BLE001 — record then re-raise for visibility
            context.add_error(f"Republish failed: {exc}")
            mark_ingestion_run_failed(context, str(exc))
            logger.exception("Republish failed for dataset_version_id=%s.", dataset_version_id)
            raise

        published = _count(
            sf, "SELECT COUNT(*) FROM cold_case.cases WHERE dataset_version_id = :dvid", dataset_version_id
        )
        logger.info(
            "Republished dataset_version_id=%s: %d cases now published.",
            dataset_version_id,
            published,
        )
        logger.info("Final summary: %s", context.to_log_dict())
        return 0
    finally:
        cleanup_context(context)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-transform + publish an existing dataset_version from intact raw.")
    parser.add_argument("--source-key", required=True, help="Source key from the declarative catalog.")
    parser.add_argument(
        "--dataset-version-id", required=True, type=int, help="The failed dataset_version to rebuild from raw."
    )
    parser.add_argument("--catalog-path", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and exit without mutating.")
    parser.add_argument("--yes", action="store_true", help="Confirm the destructive rebuild.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return republish(
        source_key=args.source_key,
        dataset_version_id=args.dataset_version_id,
        catalog_path=args.catalog_path,
        dry_run=args.dry_run,
        assume_yes=args.yes,
    )


if __name__ == "__main__":
    sys.exit(main())
