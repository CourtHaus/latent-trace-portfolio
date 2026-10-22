from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from tools.audit.model import AuditContext


def resolve_context(
    session: Session,
    *,
    source: str,
    source_code: str,
    state: str,
) -> AuditContext | None:
    """Resolve the latest published dataset_version for a source into an
    AuditContext. Returns None if the source has no published dataset_version.

    ``source`` is interpolated into the raw table name and MUST be an internal
    adapter constant (e.g. ``SourceAuditConfig.source``), never user input.
    """
    dv = session.execute(
        text("""
            SELECT dv.dataset_version_id
            FROM etl.dataset_version dv
            JOIN etl.source_system ss ON ss.source_system_id = dv.source_system_id
            WHERE ss.source_code = :code AND dv.ingestion_status = 'published'
            ORDER BY dv.published_at DESC NULLS LAST, dv.dataset_version_id DESC
            LIMIT 1
        """),
        {"code": source_code},
    ).scalar_one_or_none()
    if dv is None:
        return None

    raw_table = f"raw_cold_case.{source}_dv{dv}"
    total = session.execute(
        text("SELECT count(*) FROM cold_case.cases WHERE dataset_version_id = :dv"),
        {"dv": dv},
    ).scalar_one()
    return AuditContext(
        source=source,
        source_code=source_code,
        state=state,
        dataset_version_id=int(dv),
        raw_table=raw_table,
        total_cases=int(total),
    )
