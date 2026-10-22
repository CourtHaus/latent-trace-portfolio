from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

from casesignal.etl.adapters.cold_case_ar_asp.adapter import (
    ColdCaseARASPAdapter,
)
from casesignal.etl.adapters.cold_case_co.adapter import (
    ColdCaseCOAdapter,
)
from casesignal.etl.adapters.cold_case_dc_mpdc.adapter import (
    ColdCaseDCMPDCAdapter,
)
from casesignal.etl.adapters.cold_case_fl_fdle.adapter import (
    ColdCaseFLFDLEAdapter,
)
from casesignal.etl.adapters.cold_case_md_anne_arundel.adapter import (
    ColdCaseMDAnneArundelAdapter,
)
from casesignal.etl.adapters.cold_case_md_baltimore_county.adapter import (
    ColdCaseMDBaltimoreCountyAdapter,
)
from casesignal.etl.adapters.cold_case_md_charles.adapter import (
    ColdCaseMDCharlesAdapter,
)
from casesignal.etl.adapters.cold_case_md_harford.adapter import (
    ColdCaseMDHarfordAdapter,
)
from casesignal.etl.adapters.cold_case_md_howard.adapter import (
    ColdCaseMDHowardAdapter,
)
from casesignal.etl.adapters.cold_case_md_wicomico.adapter import (
    ColdCaseMDWicomicoAdapter,
)
from casesignal.etl.adapters.cold_case_mn_bca.adapter import ColdCaseMnBcaAdapter
from casesignal.etl.adapters.cold_case_nh_doj.adapter import (
    ColdCaseNhDojAdapter,
)
from casesignal.etl.adapters.cold_case_oh_ag.adapter import (
    ColdCaseOHAdapter,
)
from casesignal.etl.adapters.cold_case_ok_osbi.adapter import (
    ColdCaseOKOSBIAdapter,
)
from casesignal.etl.adapters.cold_case_ut.adapter import (
    ColdCaseUTAdapter,
)
from casesignal.etl.adapters.cold_case_va.adapter import ColdCaseVAAdapter
from casesignal.etl.adapters.cold_case_wy_dci.adapter import (
    ColdCaseWyDciAdapter,
)
from casesignal.etl.services.adapter_registry import AdapterRegistry
from casesignal.etl.services.db import (
    create_db_engine,
    create_session_factory,
    dispose_engine,
    test_connection,
)
from casesignal.etl.services.ingestion_tracking import mark_ingestion_run_failed
from casesignal.etl.services.normalize_dataset import normalize_dataset_stage
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_catalog import SourceCatalog
from casesignal.etl.services.source_definition import SourceDefinition

try:
    from casesignal.etl.config import settings
except ImportError as exc:
    raise RuntimeError(
        "casesignal.etl.config.settings could not be imported. Ensure your configuration is defined."
    ) from exc

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[1] / "sources"


@dataclass(frozen=True)
class PipelineRunResult:
    source_key: str
    dataset_version_id: int | None
    ingestion_run_id: int | None
    run_status: str


def configure_logging() -> logging.Logger:
    """
    Configure and return the pipeline logger.
    """
    logger = logging.getLogger("casesignal.etl.run_pipeline")
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        log_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        stream_handler.setFormatter(log_formatter)
        logger.addHandler(stream_handler)

    return logger


def build_adapter_registry() -> AdapterRegistry:
    """Build and return the application adapter registry."""

    registry = AdapterRegistry()
    registry.register(ColdCaseVAAdapter)
    registry.register(ColdCaseMDBaltimoreCountyAdapter)
    registry.register(ColdCaseMDAnneArundelAdapter)
    registry.register(ColdCaseMDHowardAdapter)
    registry.register(ColdCaseMDHarfordAdapter)
    registry.register(ColdCaseMDCharlesAdapter)
    registry.register(ColdCaseMDWicomicoAdapter)
    registry.register(ColdCaseCOAdapter)
    registry.register(ColdCaseUTAdapter)
    registry.register(ColdCaseDCMPDCAdapter)
    registry.register(ColdCaseOHAdapter)
    registry.register(ColdCaseWyDciAdapter)
    registry.register(ColdCaseNhDojAdapter)
    registry.register(ColdCaseMnBcaAdapter)
    registry.register(ColdCaseFLFDLEAdapter)
    registry.register(ColdCaseARASPAdapter)
    registry.register(ColdCaseOKOSBIAdapter)
    return registry


def resolve_source_definition(
    source_key: str,
    catalog_path: Path,
) -> SourceDefinition:
    catalog = SourceCatalog.from_yaml(catalog_path)
    return catalog.get(source_key)


def build_pipeline_context(
    source_definition: SourceDefinition,
    logger: logging.Logger,
) -> PipelineContext:
    """
    Build a PipelineContext from a resolved SourceDefinition.
    """
    context = PipelineContext(
        source_key=source_definition.source_key,
        source_family=source_definition.source_family,
        source_code=source_definition.source_code,
        source_name=source_definition.source_name,
        source_year=source_definition.source_year,
        source_state=source_definition.source_state,
        source_path=source_definition.input_path,
        logger=logger,
    )

    context.set_metadata("source_definition", source_definition.to_dict())
    return context


def attach_database(context: PipelineContext) -> None:
    """
    Initialize database resources and attach them to the pipeline context.
    """
    engine = create_db_engine(
        settings.database_url,
        echo=settings.sqlalchemy_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        application_name=settings.database_application_name,
        statement_timeout_ms=settings.database_statement_timeout_ms,
        lock_timeout_ms=settings.database_lock_timeout_ms,
    )
    session_factory = create_session_factory(engine)

    context.engine = engine
    context.set_metadata("session_factory", session_factory)


def cleanup_context(context: PipelineContext) -> None:
    """Dispose of database resources associated with the context."""
    logger = context.logger
    assert logger is not None

    if context.engine is not None:
        dispose_engine(context.engine)
        logger.info("Disposed database engine.")


def run_pipeline(source_key: str, catalog_path: Path) -> PipelineRunResult:
    """
    Execute the ingestion pipeline for the given source key.
    """
    logger = configure_logging()

    logger.info("Loading source catalog from '%s'.", catalog_path)
    source_definition = resolve_source_definition(
        source_key=source_key,
        catalog_path=catalog_path,
    )

    logger.info(
        "Resolved source definition for key '%s' : %s",
        source_key,
        source_definition.to_dict(),
    )

    return run_source_definition(source_definition=source_definition, logger=logger)


def run_source_definition(
    source_definition: SourceDefinition,
    logger: logging.Logger | None = None,
) -> PipelineRunResult:
    """
    Execute the ingestion pipeline for a resolved source definition.
    """
    logger = logger or configure_logging()

    context = build_pipeline_context(source_definition=source_definition, logger=logger)

    registry = build_adapter_registry()
    adapter = registry.create_adapter(source_definition)

    logger.info(
        "Using adapter '%s' for source '%s'.",
        source_definition.adapter_name,
        source_definition.source_key,
    )

    try:
        attach_database(context)
        test_connection(context.require_engine())
        logger.info("Database connectivity test succeeded.")

        adapter.run_stage(context, "prepare_input", adapter.prepare_input)
        adapter.run_stage(context, "register_source", adapter.register_source)
        adapter.run_stage(context, "load_raw", adapter.load_raw)
        adapter.run_stage(context, "transform", adapter.transform)
        # Shared canonicalization — lifted out of per-adapter transforms so it
        # always runs (no 6-of-10 gaps). Normalizes the just-written dataset's
        # case_type / victim gender / victim race via the shared normalizers.
        adapter.run_stage(context, "normalize", normalize_dataset_stage)
        adapter.run_stage(context, "publish", adapter.publish)

        logger.info("Pipeline completed successfully.")
        logger.info("Final pipeline summary: %s", context.to_log_dict())
        return PipelineRunResult(
            source_key=source_definition.source_key,
            dataset_version_id=context.dataset_version_id,
            ingestion_run_id=context.ingestion_run_id,
            run_status="succeeded",
        )

    except Exception as exc:
        context.add_error(f"Pipeline failed: {exc}")
        mark_ingestion_run_failed(context, str(exc))
        logger.exception("Pipeline execution failed for source '%s'.", source_definition.source_key)
        raise
    finally:
        cleanup_context(context)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments
    """
    parser = argparse.ArgumentParser(
        description="Run the CaseSignal ingestion pipeline for a configured source."
    )
    parser.add_argument(
        "--source-key",
        required=True,
        help="Source key from the declarative source catalog.",
    )
    parser.add_argument(
        "--catalog-path",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help=f"Path to the source catalog YAML file. Defaults to {DEFAULT_CATALOG_PATH}.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_pipeline(
        source_key=args.source_key,
        catalog_path=args.catalog_path,
    )


if __name__ == "__main__":
    main()
