"""DB helpers for case_extractions + selection queries."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.extraction.cold_case.extract_case import CaseExtraction
from casesignal.extraction.cold_case.tier2_extract_case import (
    CaseTier2Extraction,
)
from casesignal.extraction.cold_case.tier_policy import TIER2_DISABLED_STATES


@dataclass(frozen=True)
class CaseNeedingExtraction:
    case_id: int
    about_text: str


def insert_extraction(session: Session, extraction: CaseExtraction) -> None:
    """Write a single Tier-1 CaseExtraction row. Caller controls commit."""
    session.execute(
        text("""
            INSERT INTO cold_case.case_extractions (
                case_id, prompt_tier, extractor_version, prompt_hash, model_id,
                raw_llm_response, prompt_tokens, completion_tokens, cost_usd, notes,
                weapon, weapon_raw_phrase, weapon_source_start, weapon_source_end, weapon_low_confidence,
                location_type, location_type_raw_phrase, location_type_source_start, location_type_source_end, location_type_low_confidence
            )
            VALUES (
                :case_id, 1, :extractor_version, :prompt_hash, :model_id,
                :raw_llm_response, :prompt_tokens, :completion_tokens, :cost_usd, :notes,
                :weapon, :weapon_raw_phrase, :weapon_source_start, :weapon_source_end, :weapon_low_confidence,
                :location_type, :location_type_raw_phrase, :location_type_source_start, :location_type_source_end, :location_type_low_confidence
            )
            ON CONFLICT (case_id, prompt_hash, model_id, prompt_tier) DO NOTHING
        """),
        {
            "case_id": extraction.case_id,
            "extractor_version": extraction.extractor_version,
            "prompt_hash": extraction.prompt_hash,
            "model_id": extraction.model_id,
            "raw_llm_response": (
                json.dumps(extraction.raw_llm_response)
                if extraction.raw_llm_response is not None
                else None
            ),
            "prompt_tokens": extraction.prompt_tokens,
            "completion_tokens": extraction.completion_tokens,
            "cost_usd": extraction.cost_usd,
            "notes": extraction.notes,
            "weapon": extraction.weapon.value,
            "weapon_raw_phrase": extraction.weapon.raw_phrase,
            "weapon_source_start": extraction.weapon.source_start,
            "weapon_source_end": extraction.weapon.source_end,
            "weapon_low_confidence": extraction.weapon.low_confidence,
            "location_type": extraction.location_type.value,
            "location_type_raw_phrase": extraction.location_type.raw_phrase,
            "location_type_source_start": extraction.location_type.source_start,
            "location_type_source_end": extraction.location_type.source_end,
            "location_type_low_confidence": extraction.location_type.low_confidence,
        },
    )


def insert_tier2_extraction(session: Session, extraction: CaseTier2Extraction) -> None:
    """Write a single Tier-2 CaseTier2Extraction row.

    Stored alongside Tier-1 rows in cold_case.case_extractions but with
    prompt_tier=2. The Tier-1 columns (weapon, location_type) are NULL on
    these rows; the Tier-2 columns are populated.

    Caller controls commit.
    """
    session.execute(
        text("""
            INSERT INTO cold_case.case_extractions (
                case_id, prompt_tier, extractor_version, prompt_hash, model_id,
                raw_llm_response, prompt_tokens, completion_tokens, cost_usd, notes,
                incident_date_text, incident_date_raw_phrase,
                  incident_date_source_start, incident_date_source_end,
                  incident_date_low_confidence,
                address_text, address_raw_phrase,
                  address_source_start, address_source_end,
                  address_low_confidence,
                victim_age_text, victim_age_raw_phrase,
                  victim_age_source_start, victim_age_source_end,
                  victim_age_low_confidence,
                victim_gender_text, victim_gender_raw_phrase,
                  victim_gender_source_start, victim_gender_source_end,
                  victim_gender_low_confidence
            )
            VALUES (
                :case_id, 2, :extractor_version, :prompt_hash, :model_id,
                :raw_llm_response, :prompt_tokens, :completion_tokens, :cost_usd, :notes,
                :incident_date_text, :incident_date_raw_phrase,
                  :incident_date_source_start, :incident_date_source_end,
                  :incident_date_low_confidence,
                :address_text, :address_raw_phrase,
                  :address_source_start, :address_source_end,
                  :address_low_confidence,
                :victim_age_text, :victim_age_raw_phrase,
                  :victim_age_source_start, :victim_age_source_end,
                  :victim_age_low_confidence,
                :victim_gender_text, :victim_gender_raw_phrase,
                  :victim_gender_source_start, :victim_gender_source_end,
                  :victim_gender_low_confidence
            )
            ON CONFLICT (case_id, prompt_hash, model_id, prompt_tier) DO NOTHING
        """),
        {
            "case_id": extraction.case_id,
            "extractor_version": extraction.extractor_version,
            "prompt_hash": extraction.prompt_hash,
            "model_id": extraction.model_id,
            "raw_llm_response": (
                json.dumps(extraction.raw_llm_response)
                if extraction.raw_llm_response is not None
                else None
            ),
            "prompt_tokens": extraction.prompt_tokens,
            "completion_tokens": extraction.completion_tokens,
            "cost_usd": extraction.cost_usd,
            "notes": extraction.notes,
            "incident_date_text": extraction.incident_date.value,
            "incident_date_raw_phrase": extraction.incident_date.raw_phrase,
            "incident_date_source_start": extraction.incident_date.source_start,
            "incident_date_source_end": extraction.incident_date.source_end,
            "incident_date_low_confidence": extraction.incident_date.low_confidence,
            "address_text": extraction.address.value,
            "address_raw_phrase": extraction.address.raw_phrase,
            "address_source_start": extraction.address.source_start,
            "address_source_end": extraction.address.source_end,
            "address_low_confidence": extraction.address.low_confidence,
            "victim_age_text": (
                str(extraction.victim_age.value)
                if extraction.victim_age.value is not None
                else None
            ),
            "victim_age_raw_phrase": extraction.victim_age.raw_phrase,
            "victim_age_source_start": extraction.victim_age.source_start,
            "victim_age_source_end": extraction.victim_age.source_end,
            "victim_age_low_confidence": extraction.victim_age.low_confidence,
            "victim_gender_text": extraction.victim_gender.value,
            "victim_gender_raw_phrase": extraction.victim_gender.raw_phrase,
            "victim_gender_source_start": extraction.victim_gender.source_start,
            "victim_gender_source_end": extraction.victim_gender.source_end,
            "victim_gender_low_confidence": extraction.victim_gender.low_confidence,
        },
    )


def insert_victim_extractions(session: Session, extraction: CaseTier2Extraction) -> None:
    """Write one cold_case.victim_extraction row per roster victim.

    Idempotent via the (case_id, model_id, prompt_hash, victim_ordinal) unique
    constraint: ON CONFLICT DO NOTHING. victim_id is left NULL (linked later by
    reconciliation). Caller controls commit.
    """
    for v in extraction.victims:
        session.execute(
            text("""
                INSERT INTO cold_case.victim_extraction (
                    case_id, victim_ordinal, model_id, prompt_hash, prompt_tier,
                    name_text, name_raw_phrase, name_source_start, name_source_end, name_low_confidence,
                    victim_age_text, victim_age_raw_phrase, victim_age_source_start,
                      victim_age_source_end, victim_age_low_confidence,
                    victim_gender_text, victim_gender_raw_phrase, victim_gender_source_start,
                      victim_gender_source_end, victim_gender_low_confidence
                ) VALUES (
                    :cid, :ord, :model_id, :prompt_hash, 2,
                    :nt, :nrp, :nss, :nse, :nlc,
                    :at, :arp, :ass, :ase, :alc,
                    :gt, :grp, :gss, :gse, :glc
                )
                ON CONFLICT (case_id, model_id, prompt_hash, victim_ordinal) DO NOTHING
            """),
            {
                "cid": extraction.case_id,
                "ord": v.ordinal,
                "model_id": extraction.model_id,
                "prompt_hash": extraction.prompt_hash,
                "nt": v.name.value,
                "nrp": v.name.raw_phrase,
                "nss": v.name.source_start,
                "nse": v.name.source_end,
                "nlc": v.name.low_confidence,
                "at": (
                    str(v.victim_age.value) if v.victim_age.value is not None else None
                ),
                "arp": v.victim_age.raw_phrase,
                "ass": v.victim_age.source_start,
                "ase": v.victim_age.source_end,
                "alc": v.victim_age.low_confidence,
                "gt": v.victim_gender.value,
                "grp": v.victim_gender.raw_phrase,
                "gss": v.victim_gender.source_start,
                "gse": v.victim_gender.source_end,
                "glc": v.victim_gender.low_confidence,
            },
        )


def backfill_canonical_values_from_tier2(
    session: Session,
    extraction: CaseTier2Extraction,
) -> None:
    """Populate cold_case.cases NULL canonical fields from Tier-2.

    Only writes to a column when it's currently NULL (preserves source-
    structured values like VA's CSV-supplied incident_date / address).
    Tier-2 victim demographic values remain extraction/provenance data only:
    they are case-level model outputs, not victim-identity-bound facts. Writing
    one extracted age/gender/race by case_id can pollute every victim row on
    multi-victim cases and can turn low-confidence model output into canonical
    public data.

    Caller controls commit.
    """
    case_id = extraction.case_id

    if extraction.incident_date.value:
        session.execute(
            text("""
                UPDATE cold_case.cases
                   SET incident_date = :date,
                       incident_date_source = 'tier2'
                 WHERE case_id = :cid
                   AND incident_date IS NULL
            """),
            {"date": extraction.incident_date.value, "cid": case_id},
        )

    if extraction.address.value:
        session.execute(
            text("""
                UPDATE cold_case.cases
                   SET address = :addr,
                       address_source = 'tier2'
                 WHERE case_id = :cid
                   AND address IS NULL
            """),
            {"addr": extraction.address.value, "cid": case_id},
        )


def enqueue_geocoding_job_from_tier2(
    session: Session,
    extraction: CaseTier2Extraction,
    *,
    state_code: str | None = None,
    county_fips: str | None = None,
) -> None:
    """Enqueue a geocoding job using the Tier-2-extracted address.

    Skips when:
      - address was not extracted (address.value is None)
      - case is already at street/landmark/zip precision (no improvement possible)

    Fires when current precision is NULL, 'failed', or 'county' — where Tier-2's
    extracted address could plausibly upgrade the pin.

    Caller controls commit.
    """
    import re

    address = extraction.address.value
    if not address:
        return

    row = session.execute(
        text("SELECT geocode_precision FROM cold_case.cases WHERE case_id = :cid"),
        {"cid": extraction.case_id},
    ).first()
    current = row.geocode_precision if row else None
    if current in ("street", "landmark", "zip"):
        return

    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", address)
    zip_code = zip_match.group(1) if zip_match else None

    session.execute(
        text("""
            INSERT INTO cold_case.geocoding_job
                (case_id, address_text, state_code, zip_code, county_fips)
            VALUES (:cid, :addr, :state, :zip, :fips)
        """),
        {
            "cid": extraction.case_id,
            "addr": address,
            "state": state_code,
            "zip": zip_code,
            "fips": county_fips,
        },
    )


def extraction_exists_for(
    session: Session,
    case_id: int,
    prompt_hash: str,
    model_id: str,
    prompt_tier: int = 1,
) -> bool:
    """Idempotency check: does a row exist at (case_id, prompt_hash, model_id, tier)?"""
    row = session.execute(
        text("""
            SELECT 1 FROM cold_case.case_extractions
             WHERE case_id = :case_id
               AND prompt_hash = :prompt_hash
               AND model_id = :model_id
               AND prompt_tier = :prompt_tier
             LIMIT 1
        """),
        {
            "case_id": case_id,
            "prompt_hash": prompt_hash,
            "model_id": model_id,
            "prompt_tier": prompt_tier,
        },
    ).first()
    return row is not None


def find_cases_needing_extraction(
    session: Session,
    prompt_hash: str,
    model_id: str,
    *,
    prompt_tier: int = 1,
    dataset_version_id: int | None = None,
    state: str | None = None,
    limit: int | None = None,
) -> list[CaseNeedingExtraction]:
    """Return cases that lack an extraction at (prompt_hash, model_id, tier).

    Used by the CLI to build the work queue. Queue worker uses extraction_job
    claims, not this query — but the CLI re-uses find_cases_needing_extraction
    to filter which jobs to enqueue on a re-run.
    """
    sql = """
        SELECT case_id, about_text
          FROM cold_case.cases c
         WHERE c.about_text IS NOT NULL AND c.about_text != ''
    """
    params: dict[str, object] = {
        "prompt_hash": prompt_hash,
        "model_id": model_id,
        "prompt_tier": prompt_tier,
    }
    if dataset_version_id is not None:
        sql += "\n           AND c.dataset_version_id = :dv"
        params["dv"] = dataset_version_id
    if state is not None:
        sql += "\n           AND c.state = :state"
        params["state"] = state
    if prompt_tier == 2:
        sql += "\n           AND (c.state IS NULL OR c.state <> ALL(:tier2_disabled_states))"
        params["tier2_disabled_states"] = sorted(TIER2_DISABLED_STATES)
    sql += """
           AND NOT EXISTS (
             SELECT 1 FROM cold_case.case_extractions e
              WHERE e.case_id = c.case_id
                AND e.prompt_hash = :prompt_hash
                AND e.model_id = :model_id
                AND e.prompt_tier = :prompt_tier
           )
         ORDER BY c.case_id
    """
    if limit is not None:
        sql += "\n         LIMIT :limit"
        params["limit"] = limit

    rows = session.execute(text(sql), params).all()
    return [CaseNeedingExtraction(case_id=r.case_id, about_text=r.about_text) for r in rows]
