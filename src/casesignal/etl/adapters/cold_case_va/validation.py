"""Validation stages for cold_case_va ingestion."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from casesignal.etl.services.pipeline_context import PipelineContext


def validate_cold_case_raw(context: PipelineContext) -> None:
    logger = context.logger
    if logger is None:
        raise RuntimeError("PipelineContext.logger must be set before running stages.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError(
            "session_factory in pipeline context metadata is not a SQLAlchemy sessionmaker."
        )

    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set.")

    raw_table = f"raw_cold_case.cases_dv{context.dataset_version_id}"

    with session_factory() as session:
        count = session.execute(
            text(f"SELECT COUNT(*) FROM {raw_table} WHERE dataset_version_id = :dv"),
            {"dv": context.dataset_version_id},
        ).scalar_one()

        if count == 0:
            raise RuntimeError(
                f"load_raw: raw table {raw_table} has zero rows for "
                f"dataset_version_id={context.dataset_version_id}"
            )

        # Alert on implausibly-large or implausibly-small datasets; 2025-03-27 had 830.
        # 100 is a safety floor that would catch a broken parse; 50000 is a ceiling.
        if count < 100 or count > 50000:
            logger.warning(
                "load_raw: row count %d outside expected range [100, 50000] for %s",
                count,
                raw_table,
            )

        logger.info("load_raw: %d rows OK in %s", count, raw_table)


def validate_cold_case_core(context: PipelineContext) -> None:
    logger = context.logger
    if logger is None:
        raise RuntimeError("PipelineContext.logger must be set before running stages.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError(
            "session_factory in pipeline context metadata is not a SQLAlchemy sessionmaker."
        )

    with session_factory() as session:
        cases_count = session.execute(
            text("SELECT COUNT(*) FROM cold_case.cases WHERE dataset_version_id = :dv"),
            {"dv": context.dataset_version_id},
        ).scalar_one()

        orphan_victims = session.execute(text("""
                SELECT COUNT(*) FROM cold_case.victim v
                LEFT JOIN cold_case.cases c ON c.case_id = v.case_id
                WHERE c.case_id IS NULL
                """)).scalar_one()

        orphan_contacts = session.execute(text("""
                SELECT COUNT(*) FROM cold_case.contact ct
                LEFT JOIN cold_case.cases c ON c.case_id = ct.case_id
                WHERE c.case_id IS NULL
                """)).scalar_one()

        if orphan_victims > 0:
            raise RuntimeError(f"transform: {orphan_victims} orphan victim rows detected.")
        if orphan_contacts > 0:
            raise RuntimeError(f"transform: {orphan_contacts} orphan contact rows detected.")

        if cases_count == 0:
            raise RuntimeError("transform: zero cases produced by transform.")

        # Date-coverage ratio: catches a silent parser break (all dates NULL).
        # Threshold set to 0.80 because some historical VA cases legitimately
        # lack an incident_date ("unknown date" in the source narrative).
        dated = session.execute(
            text("""
                SELECT COUNT(*) FROM cold_case.cases
                WHERE dataset_version_id = :dv AND incident_date IS NOT NULL
                """),
            {"dv": context.dataset_version_id},
        ).scalar_one()
        date_coverage = dated / cases_count if cases_count else 0
        if date_coverage < 0.80:
            raise RuntimeError(
                f"transform: incident_date coverage {date_coverage:.1%} < 80% "
                f"({dated}/{cases_count}); suspect date parser regression."
            )

        logger.info(
            "validate_core OK: %d cases, %.1f%% with incident_date, no orphan victims/contacts for dv=%s",
            cases_count,
            date_coverage * 100,
            context.dataset_version_id,
        )
