"""Shared transform-stage helpers for MD-county adapters.

Insert helpers for cold_case.cases / victim / contact / case_photo
(MD-defaulted) plus extraction-job enqueue. Each helper is a pure
function: takes a Session + parameters, returns the inserted ID where
relevant. Caller controls commit.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.cold_case.slug import build_case_slug, resolve_slug_collision
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
    load_tier2_v4_prompt_template,
)
from casesignal.extraction.cold_case.queue_handler import enqueue_extraction_job

# Pinned at module load: every transform run uses a consistent
# (prompt_hash, model_id, tier) tuple. Tier-2 uses v2 (with race) for
# all NEW MD ingestions; existing Phase 1 BCounty rows keep their v1
# prompt_hash on disk in case_extractions.
_TIER1_PROMPT_HASH = compute_prompt_hash(load_tier1_prompt_template())
_TIER2_PROMPT_HASH = compute_prompt_hash(load_tier2_v4_prompt_template())
_PINNED_MODEL_ID = get_pinned_model_id()


@dataclass(frozen=True)
class PhotoMetadata:
    """Per-case photo metadata to insert into cold_case.case_photo."""

    filename: str
    content_type: str
    sha256: str
    source_url: str | None
    alt_text: str | None = None
    is_primary: bool = True


_CASE_LOOKUP_SQL = text("""
    SELECT case_id FROM cold_case.cases
    WHERE dataset_version_id = :dv AND source_case_id = :scid
""")


def insert_md_case(
    session: Session,
    *,
    dataset_version_id: int,
    source_case_id: str,
    case_name: str,
    case_year: int | None,
    state: str,
    city: str,
    county_fips: str,
    about_text: str,
) -> tuple[int, bool]:
    """Insert one cold_case.cases row for an MD county source.

    Resolves slug collision via the shared slug helper. Returns
    ``(case_id, is_new)`` where ``is_new=False`` means the row already
    existed (idempotent re-run); callers should skip dependent inserts
    (victim / contact / photo / extraction jobs) when ``is_new=False``.
    """
    slug_base = build_case_slug(case_name=case_name, city=city, state=state, year=case_year)
    slug = resolve_slug_collision(session, slug_base)
    case_id = session.execute(
        text("""
            INSERT INTO cold_case.cases (
                dataset_version_id, source_case_id, slug,
                case_name, case_type, state, city, source_county_fips,
                about_text, latitude, longitude, geocode_precision
            )
            VALUES (
                :dv, :scid, :slug,
                :name, 'homicide', :state, :city, :fips,
                :about, NULL, NULL, NULL
            )
            ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
            RETURNING case_id
        """),
        {
            "dv": dataset_version_id,
            "scid": source_case_id,
            "slug": slug,
            "name": case_name,
            "state": state,
            "city": city,
            "fips": county_fips,
            "about": about_text,
        },
    ).scalar_one_or_none()

    if case_id is None:
        # Row already exists — look it up and signal caller to skip dependents.
        case_id = session.execute(
            _CASE_LOOKUP_SQL, {"dv": dataset_version_id, "scid": source_case_id}
        ).scalar_one()
        return case_id, False

    return case_id, True


def insert_md_victims(
    session: Session,
    *,
    case_id: int,
    victim_names: list[tuple[str, str]],
) -> int:
    """Insert one row per (first_name, last_name) into cold_case.victim.

    Returns the count inserted.
    """
    inserted = 0
    for first, last in victim_names:
        session.execute(
            text("""
                INSERT INTO cold_case.victim (case_id, first_name, last_name)
                VALUES (:cid, :first, :last)
            """),
            {"cid": case_id, "first": first, "last": last},
        )
        inserted += 1
    return inserted


def insert_md_contact(
    session: Session,
    *,
    case_id: int,
    email: str | None,
    phone: str | None,
    address: str,
) -> None:
    """Insert one cold_case.contact row for an MD county source.

    The phone column exists on cold_case.contact (confirmed 2026-05-08).
    """
    session.execute(
        text("""
            INSERT INTO cold_case.contact (case_id, email, phone, address)
            VALUES (:cid, :email, :phone, :addr)
        """),
        {"cid": case_id, "email": email, "phone": phone, "addr": address},
    )


def insert_md_case_photo(
    session: Session,
    *,
    case_id: int,
    photo: PhotoMetadata,
    adapter_dir: str,
    source_case_id: str,
) -> None:
    """Insert one cold_case.case_photo row.

    Defensive: coalesces a None/empty content_type to
    'application/octet-stream' before writing to satisfy the NOT NULL
    column on cold_case.case_photo.

    ``adapter_dir`` is the adapter's photos root directory (e.g.
    ``"cold_case_md_baltimore_county"``); ``source_case_id`` is the
    verbatim cases.source_case_id for this row. Together they form:
    ``storage_path = "<adapter_dir>/<source_case_id>/<filename>"``.
    """
    content_type = photo.content_type or "application/octet-stream"
    storage_path = f"{adapter_dir}/{source_case_id}/{photo.filename}"
    session.execute(
        text("""
            INSERT INTO cold_case.case_photo
                (case_id, filename, content_type, alt_text,
                 sha256, is_primary, source_url, storage_path)
            VALUES
                (:cid, :filename, :ctype, :alt,
                 :sha, :is_primary, :src, :storage_path)
        """),
        {
            "cid": case_id,
            "filename": photo.filename,
            "ctype": content_type,
            "alt": photo.alt_text,
            "sha": photo.sha256,
            "is_primary": photo.is_primary,
            "src": photo.source_url,
            "storage_path": storage_path,
        },
    )


_EXTRACTION_JOB_EXISTS_SQL = text("""
    SELECT 1 FROM cold_case.extraction_job
    WHERE case_id = :case_id AND prompt_tier = :prompt_tier
    LIMIT 1
""")


def enqueue_md_extraction_jobs(session: Session, *, case_id: int) -> int:
    """Enqueue Tier-1 + Tier-2 extraction jobs for ``case_id``.

    Skips tiers where a job already exists (any status) so re-runs don't
    create duplicate jobs. Returns the number of jobs actually inserted (0–2).
    """
    inserted = 0
    for tier, prompt_hash in (
        (1, _TIER1_PROMPT_HASH),
        (2, _TIER2_PROMPT_HASH),
    ):
        already = session.execute(
            _EXTRACTION_JOB_EXISTS_SQL, {"case_id": case_id, "prompt_tier": tier}
        ).first()
        if already is not None:
            continue
        enqueue_extraction_job(
            session,
            case_id=case_id,
            prompt_hash=prompt_hash,
            model_id=_PINNED_MODEL_ID,
            prompt_tier=tier,
        )
        inserted += 1
    return inserted
