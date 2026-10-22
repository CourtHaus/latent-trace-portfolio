"""Transform stage for the Anne Arundel adapter.

Reads raw_cold_case.cold_case_md_anne_arundel_dv<N> and uses
cold_case_md_shared.transform_helpers for the standard MD-county
inserts. AA's source presents each victim under their own h3, so the
default 1:1 case→victim mapping applies; no multi-victim allowlist.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from casesignal.etl.adapters.cold_case_md_shared.constants import (
    MD_COUNTY_DISPLAY,
    MD_COUNTY_FIPS,
    MD_STATE,
)
from casesignal.etl.adapters.cold_case_md_shared.transform_helpers import (
    PhotoMetadata,
    enqueue_md_extraction_jobs,
    insert_md_case,
    insert_md_case_photo,
    insert_md_contact,
    insert_md_victims,
)
from casesignal.etl.services.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)


_AA_KEY = "anne_arundel"
# Anne Arundel County PD Homicide Unit. Department-level contact only;
# per-case detective contact is not exposed on the source page.
_AA_CONTACT_EMAIL = None  # AA does not list an email for the unit
_AA_CONTACT_PHONE = "410-222-4731"
_AA_CONTACT_ADDRESS = (
    "Anne Arundel County Police Department, Homicide Unit, "
    "8495 Veterans Highway, Millersville, Maryland 21108"
)


def transform_aa(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_md_anne_arundel_dv{context.dataset_version_id}"

    cases_inserted = 0
    victims_inserted = 0
    photos_inserted = 0
    extraction_jobs_enqueued = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT source_case_id, case_name, narrative_text,
                           photo_filename, photo_content_type, photo_alt_text,
                           photo_source_url, photo_sha256
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                victim_pairs = _parse_victim_name(r.case_name)

                case_id, is_new = insert_md_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=r.case_name,
                    case_year=None,  # AA narratives state year in prose; Tier-2 extracts
                    state=MD_STATE,
                    city=MD_COUNTY_DISPLAY[_AA_KEY],
                    county_fips=MD_COUNTY_FIPS[_AA_KEY],
                    about_text=r.narrative_text,
                )
                if is_new:
                    cases_inserted += 1

                    insert_md_contact(
                        session,
                        case_id=case_id,
                        email=_AA_CONTACT_EMAIL,
                        phone=_AA_CONTACT_PHONE,
                        address=_AA_CONTACT_ADDRESS,
                    )

                    victims_inserted += insert_md_victims(
                        session, case_id=case_id, victim_names=victim_pairs
                    )

                    if r.photo_filename and r.photo_sha256:
                        insert_md_case_photo(
                            session,
                            case_id=case_id,
                            photo=PhotoMetadata(
                                filename=r.photo_filename,
                                content_type=r.photo_content_type,
                                sha256=r.photo_sha256,
                                source_url=r.photo_source_url,
                                alt_text=r.photo_alt_text,
                                is_primary=True,
                            ),
                            adapter_dir="cold_case_md_anne_arundel",
                            source_case_id=r.source_case_id,
                        )
                        photos_inserted += 1

                extraction_jobs_enqueued += enqueue_md_extraction_jobs(session, case_id=case_id)

            session.commit()
        except Exception:
            session.rollback()
            raise

    context.increment_row_count("transform", cases_inserted)
    if context.logger is not None:
        context.logger.info(
            "AA transform: %d cases, %d victims, %d photos, %d extraction jobs",
            cases_inserted,
            victims_inserted,
            photos_inserted,
            extraction_jobs_enqueued,
        )


def _parse_victim_name(case_name: str) -> list[tuple[str, str]]:
    """AA uses h3 = full victim name. Split on whitespace; first token is
    first_name, last token is last_name, middle tokens are part of first_name.

    Falls back to a single 'Unknown Unknown' victim if case_name is empty
    (shouldn't happen — load_raw guarantees non-empty case_name — but
    defensive).

    Special-case: case_name 'Unknown' (from C1's case-number-in-h3 sections)
    produces a single ('Unknown', '') victim.
    """
    parts = [p.strip() for p in case_name.split() if p.strip()]
    if not parts:
        return [("Unknown", "")]
    if len(parts) == 1:
        return [(parts[0], "")]
    last = parts[-1]
    first = " ".join(parts[:-1])
    return [(first, last)]
