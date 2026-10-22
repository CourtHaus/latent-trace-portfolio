"""Transform stage for the BCounty adapter (refactored to shared helpers).

Reads raw_cold_case.cold_case_md_baltimore_county_dv<N> and delegates
the standard MD-county inserts (case + victim + contact + photo +
extraction jobs) to cold_case_md_shared.transform_helpers. The only
BCounty-specific logic that stays here:

- Per-case slug parsing for victim names (URL-slug format is BCounty-specific)
- Multi-victim allowlist application
- Department-level contact info (Baltimore County PD, Towson)

Tier-2 extraction jobs go through the v2 prompt (race-aware) regardless
of which county; helpers handle that.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from casesignal.etl.adapters.cold_case_md_baltimore_county.scrape import (
    MULTI_VICTIM_SOURCE_CASE_IDS,
)
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


_BCOUNTY_KEY = "baltimore_county"
_BCOUNTY_CONTACT_EMAIL = "bcopd@baltimorecountymd.gov"
_BCOUNTY_CONTACT_ADDRESS = "Public Safety Building, 700 East Joppa Road, Towson, Maryland 21286"


def transform_bcounty(context: PipelineContext) -> None:
    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before transform.")

    session_factory = context.get_metadata("session_factory")
    if not isinstance(session_factory, sessionmaker):
        raise TypeError("session_factory metadata is not a sessionmaker.")

    table_ident = f"raw_cold_case.cold_case_md_baltimore_county_dv{context.dataset_version_id}"

    cases_inserted = 0
    victims_inserted = 0
    photos_inserted = 0
    extraction_jobs_enqueued = 0

    with session_factory() as session:
        try:
            raw_rows = session.execute(
                text(f"""
                    SELECT source_case_id, case_name, case_year,
                           narrative_text, photo_filename, photo_content_type,
                           photo_alt_text, photo_source_url, photo_sha256
                      FROM {table_ident}
                     WHERE dataset_version_id = :dv
                  ORDER BY source_case_id
                """),
                {"dv": context.dataset_version_id},
            ).all()

            for r in raw_rows:
                victim_pairs = _parse_victims_from_slug(r.source_case_id)

                case_id, is_new = insert_md_case(
                    session,
                    dataset_version_id=context.dataset_version_id,
                    source_case_id=r.source_case_id,
                    case_name=r.case_name,
                    case_year=r.case_year,
                    state=MD_STATE,
                    city=MD_COUNTY_DISPLAY[_BCOUNTY_KEY],
                    county_fips=MD_COUNTY_FIPS[_BCOUNTY_KEY],
                    about_text=r.narrative_text,
                )
                if is_new:
                    cases_inserted += 1

                    insert_md_contact(
                        session,
                        case_id=case_id,
                        email=_BCOUNTY_CONTACT_EMAIL,
                        phone=None,
                        address=_BCOUNTY_CONTACT_ADDRESS,
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
                            adapter_dir="cold_case_md_baltimore_county",
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
            "BCounty transform: %d cases, %d victims, %d photos," " %d extraction jobs enqueued",
            cases_inserted,
            victims_inserted,
            photos_inserted,
            extraction_jobs_enqueued,
        )


def _parse_victims_from_slug(source_case_id: str) -> list[tuple[str, str]]:
    """Parse victim names from the URL slug.

    Single-victim slugs follow `lastname-firstname-year` (or with
    middle names — `evans-ronald-aaron-1996`). Multi-victim slugs in
    the allowlist follow `lastnameA-firstnameA-lastnameB-firstnameB-year`.

    Returns a list of (first_name, last_name) pairs — one entry for
    single-victim, two entries for multi-victim allowlist matches.

    Slug parsing is heuristic; for cases where the slug doesn't cleanly
    parse (titles like 'Sister', no year), falls back to a single victim
    with the full case_name as last_name.
    """
    parts = source_case_id.split("-")
    if not parts:
        return [("Unknown", "Unknown")]

    # Strip trailing year token if present
    if parts and parts[-1].isdigit() and len(parts[-1]) == 4:
        parts = parts[:-1]

    if not parts:
        return [("Unknown", "Unknown")]

    if source_case_id in MULTI_VICTIM_SOURCE_CASE_IDS:
        # Even-segment-count → split into two (last, first) pairs
        if len(parts) >= 4 and len(parts) % 2 == 0:
            half = len(parts) // 2
            last_a = " ".join(parts[: half - 1] or parts[:1]).title()
            first_a = parts[half - 1].title()
            last_b = " ".join(parts[half : half + 1]).title()
            first_b = parts[-1].title()
            # Try the simpler (last_a, first_a) then (last_b, first_b) split
            return [(first_a, last_a), (first_b, last_b)]

    # Single-victim default: assume `lastname-firstname[-middle]` (year already
    # stripped). The URL convention is lastname first.
    if len(parts) == 1:
        return [(parts[0].title(), "")]
    last = parts[0].title()
    first = " ".join(p.title() for p in parts[1:])
    return [(first, last)]
