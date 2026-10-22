"""Transform stage for the Howard County adapter.

Reads raw_cold_case.cold_case_md_howard_dv<N> and uses
cold_case_md_shared.transform_helpers for the standard MD-county
inserts. Howard's source presents each victim under their own h3, so
the default 1:1 case→victim mapping applies.
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


_HOWARD_KEY = "howard"
# Howard County Police Department — department-level contact for tips.
# Per-case detective contact is not exposed on the source page.
_HOWARD_CONTACT_EMAIL = None
_HOWARD_CONTACT_PHONE = "410-313-2200"
_HOWARD_CONTACT_ADDRESS = (
    "Howard County Police Department, " "3410 Court House Drive, Ellicott City, Maryland 21043"
)


def transform_howard(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_md_howard_dv{context.dataset_version_id}"

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
                    case_year=None,  # Year is in source_case_id; Tier-2 extracts incident_date
                    state=MD_STATE,
                    city=MD_COUNTY_DISPLAY[_HOWARD_KEY],
                    county_fips=MD_COUNTY_FIPS[_HOWARD_KEY],
                    about_text=r.narrative_text,
                )
                if is_new:
                    cases_inserted += 1

                    insert_md_contact(
                        session,
                        case_id=case_id,
                        email=_HOWARD_CONTACT_EMAIL,
                        phone=_HOWARD_CONTACT_PHONE,
                        address=_HOWARD_CONTACT_ADDRESS,
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
                            adapter_dir="cold_case_md_howard",
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
            "Howard transform: %d cases, %d victims, %d photos, %d extraction jobs",
            cases_inserted,
            victims_inserted,
            photos_inserted,
            extraction_jobs_enqueued,
        )


def _parse_victim_name(case_name: str) -> list[tuple[str, str]]:
    """Howard h3 is `Homicide of <Name>, <date>` — `case_name` is the
    name part (already stripped). Split on whitespace; first tokens are
    first_name, last token is last_name.
    """
    parts = [p.strip() for p in case_name.split() if p.strip()]
    if not parts:
        return [("Unknown", "")]
    if len(parts) == 1:
        return [(parts[0], "")]
    last = parts[-1]
    first = " ".join(parts[:-1])
    return [(first, last)]
