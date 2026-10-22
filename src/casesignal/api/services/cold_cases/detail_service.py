"""Detail endpoint query — case + victims + contact + photos + extractions + correlations."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from casesignal.api.schemas.cold_cases import (
    CaseContactSection,
    CaseDetailResponse,
    CaseExtractionBlock,
    CasePhoto,
    ExtractedField,
    VictimSection,
)
from casesignal.correlation.service import find_correlated_cases


def get_cold_case_by_id(
    session: Session,
    case_id: int,
) -> CaseDetailResponse | None:
    """Return the full CaseDetailResponse with nested victims + contact +
    photos + Tier-1/Tier-2 extraction, or None if the case doesn't exist."""
    # The dataset_version JOIN gates on ingestion_status = 'published'
    # (SEC-2026-05-31-A): a case in an archived/draft/failed version resolves to
    # None here, so the endpoint 404s and none of the dependent queries run.
    case_row = (
        session.execute(
            text("""
        SELECT case_id, slug, source_case_id, case_name, case_type, incident_date,
               address, city, state, about_text, latitude, longitude,
               geocode_precision, namus_case_id, ncmec_case_id, ncic_case_id,
               address_source, incident_date_source
          FROM cold_case.cases AS cases
          JOIN etl.dataset_version dv
            ON dv.dataset_version_id = cases.dataset_version_id
           AND dv.ingestion_status = 'published'
         WHERE case_id = :case_id
    """),
            {"case_id": case_id},
        )
        .mappings()
        .one_or_none()
    )

    if case_row is None:
        return None

    victim_rows = (
        session.execute(
            text("""
        SELECT v.victim_id, v.first_name, v.last_name, v.gender, v.height_text,
               v.weight_num, v.age_text, v.age_num, v.race, v.eye_color,
               v.hair_color, v.dob, v.dod, v.ethnicity, v.tribal_affiliation,
               v.identifying_marks, v.aliases, v.occupation,
               v.age_source, v.gender_source, v.race_source,
               ve.victim_age_text        AS ext_age_text,
               ve.victim_age_raw_phrase  AS ext_age_raw_phrase,
               ve.victim_age_source_start AS ext_age_source_start,
               ve.victim_age_source_end  AS ext_age_source_end,
               ve.victim_age_low_confidence AS ext_age_low_confidence,
               ve.victim_gender_text     AS ext_gender_text,
               ve.victim_gender_raw_phrase AS ext_gender_raw_phrase,
               ve.victim_gender_source_start AS ext_gender_source_start,
               ve.victim_gender_source_end AS ext_gender_source_end,
               ve.victim_gender_low_confidence AS ext_gender_low_confidence
          FROM cold_case.victim v
          LEFT JOIN LATERAL (
                SELECT vex.victim_age_text, vex.victim_age_raw_phrase,
                       vex.victim_age_source_start, vex.victim_age_source_end,
                       vex.victim_age_low_confidence,
                       vex.victim_gender_text, vex.victim_gender_raw_phrase,
                       vex.victim_gender_source_start, vex.victim_gender_source_end,
                       vex.victim_gender_low_confidence,
                       vex.extracted_at, vex.id
                  FROM cold_case.victim_extraction vex
                 WHERE vex.victim_id = v.victim_id
                   AND vex.prompt_tier = 2
                 ORDER BY vex.extracted_at DESC, vex.id DESC
                 LIMIT 1
               ) ve ON TRUE
         WHERE v.case_id = :case_id
         ORDER BY v.victim_id
    """),
            {"case_id": case_id},
        )
        .mappings()
        .all()
    )

    contact_row = (
        session.execute(
            text("""
        SELECT phone, email, address
          FROM cold_case.contact
         WHERE case_id = :case_id
    """),
            {"case_id": case_id},
        )
        .mappings()
        .one_or_none()
    )

    # Tier-1 extraction row (weapon + location_type)
    tier1_row = (
        session.execute(
            text("""
        SELECT
            weapon, weapon_raw_phrase, weapon_source_start, weapon_source_end,
            weapon_low_confidence,
            location_type, location_type_raw_phrase, location_type_source_start,
            location_type_source_end, location_type_low_confidence,
            model_id, extracted_at
          FROM cold_case.case_extractions_current
         WHERE case_id = :case_id AND prompt_tier = 1
    """),
            {"case_id": case_id},
        )
        .mappings()
        .one_or_none()
    )

    # Tier-2 extraction row (incident_date + address). Victim age/gender
    # provenance is now per-victim via the LATERAL join on victim_extraction above.
    tier2_row = (
        session.execute(
            text("""
        SELECT
            incident_date_text, incident_date_raw_phrase,
              incident_date_source_start, incident_date_source_end,
              incident_date_low_confidence,
            address_text, address_raw_phrase,
              address_source_start, address_source_end,
              address_low_confidence
          FROM cold_case.case_extractions_current
         WHERE case_id = :case_id AND prompt_tier = 2
    """),
            {"case_id": case_id},
        )
        .mappings()
        .one_or_none()
    )

    extraction = _build_extraction_block(tier1_row, tier2_row)

    photo_rows = (
        session.execute(
            text("""
        SELECT filename, content_type, width, height, alt_text, is_primary
          FROM cold_case.case_photo
         WHERE case_id = :case_id
         ORDER BY is_primary DESC, case_photo_id ASC
    """),
            {"case_id": case_id},
        )
        .mappings()
        .all()
    )

    return CaseDetailResponse(
        **dict(case_row),
        victims=[_build_victim_section(v) for v in victim_rows],
        contact=CaseContactSection(**dict(contact_row)) if contact_row else None,
        extraction=extraction,
        correlations=find_correlated_cases(session, case_id),
        photos=[CasePhoto(**dict(p)) for p in photo_rows],
    )


def _build_extraction_block(
    tier1_row: RowMapping | None,
    tier2_row: RowMapping | None,
) -> CaseExtractionBlock | None:
    """Merge tier-1 + tier-2 rows into a single CaseExtractionBlock.

    If neither tier exists, return None. If only tier-1, populate Tier-1
    fields and leave Tier-2 fields None. If only tier-2 (rare in practice),
    return None at the block level since weapon + location_type are
    required by the schema.
    """
    if tier1_row is None:
        return None

    block = CaseExtractionBlock(
        weapon=ExtractedField(
            value=tier1_row["weapon"],
            raw_phrase=tier1_row["weapon_raw_phrase"],
            source_start=tier1_row["weapon_source_start"],
            source_end=tier1_row["weapon_source_end"],
            low_confidence=bool(tier1_row["weapon_low_confidence"]),
        ),
        location_type=ExtractedField(
            value=tier1_row["location_type"],
            raw_phrase=tier1_row["location_type_raw_phrase"],
            source_start=tier1_row["location_type_source_start"],
            source_end=tier1_row["location_type_source_end"],
            low_confidence=bool(tier1_row["location_type_low_confidence"]),
        ),
        model_id=tier1_row["model_id"],
        extracted_at=tier1_row["extracted_at"],
    )

    if tier2_row is not None:
        block = block.model_copy(
            update={
                "incident_date": ExtractedField(
                    value=tier2_row["incident_date_text"],
                    raw_phrase=tier2_row["incident_date_raw_phrase"],
                    source_start=tier2_row["incident_date_source_start"],
                    source_end=tier2_row["incident_date_source_end"],
                    low_confidence=bool(tier2_row["incident_date_low_confidence"]),
                ),
                "address": ExtractedField(
                    value=tier2_row["address_text"],
                    raw_phrase=tier2_row["address_raw_phrase"],
                    source_start=tier2_row["address_source_start"],
                    source_end=tier2_row["address_source_end"],
                    low_confidence=bool(tier2_row["address_low_confidence"]),
                ),
            }
        )

    return block


_VICTIM_COLUMNS = (
    "victim_id", "first_name", "last_name", "gender", "height_text",
    "weight_num", "age_text", "age_num", "race", "eye_color", "hair_color",
    "dob", "dod", "ethnicity", "tribal_affiliation", "identifying_marks",
    "aliases", "occupation", "age_source", "gender_source", "race_source",
)


def _build_victim_section(row: RowMapping) -> VictimSection:
    """Map a victim row (+ LATERAL extraction columns) to VictimSection.

    Extraction provenance is attached ONLY for fields whose displayed value
    came from Tier-2 (*_source == 'tier2'), so the UI can offer reveal-source
    exactly where it applies.
    """
    # Provenance is only attached when the extraction row's value matches the
    # displayed value, so a later re-extraction can't pair a stale value with a
    # fresh span.
    age_extraction = None
    if (
        row["age_source"] == "tier2"
        and row["ext_age_text"] is not None
        and row["ext_age_text"] == row["age_text"]
    ):
        age_extraction = ExtractedField(
            value=row["ext_age_text"],
            raw_phrase=row["ext_age_raw_phrase"],
            source_start=row["ext_age_source_start"],
            source_end=row["ext_age_source_end"],
            low_confidence=bool(row["ext_age_low_confidence"]),
        )
    gender_extraction = None
    if (
        row["gender_source"] == "tier2"
        and row["ext_gender_text"] is not None
        and row["ext_gender_text"] == row["gender"]
    ):
        gender_extraction = ExtractedField(
            value=row["ext_gender_text"],
            raw_phrase=row["ext_gender_raw_phrase"],
            source_start=row["ext_gender_source_start"],
            source_end=row["ext_gender_source_end"],
            low_confidence=bool(row["ext_gender_low_confidence"]),
        )
    return VictimSection(
        **{k: row[k] for k in _VICTIM_COLUMNS},
        age_extraction=age_extraction,
        gender_extraction=gender_extraction,
    )
