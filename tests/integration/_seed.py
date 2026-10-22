"""Declarative seed helper for self-seeding integration tests.

A test describes the rows it needs as CaseSpec objects, calls seed_corpus()
(which inserts a source_system + dataset_version + ingestion_run + the cases
and their dependent rows, and COMMITS so the API under test sees them via
its own connections), then relies on SeededCorpus.teardown() — or the
`seed` / `seeded_corpus` conftest fixtures — to FK-safe-delete everything.

Every corpus is keyed on a test-unique `source_code` so a crashed test's
leftover rows never collide with a fresh run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker


@dataclass
class VictimExtractionSpec:
    """A cold_case.victim_extraction row linked to its parent VictimSpec's
    victim row. Ordinal is assigned from the victim's position in
    CaseSpec.victims (1-based)."""

    name_text: str | None = None
    age_text: str | None = None
    age_raw_phrase: str | None = None
    age_source_start: int | None = None
    age_source_end: int | None = None
    age_low_confidence: bool = False
    gender_text: str | None = None
    gender_raw_phrase: str | None = None
    gender_source_start: int | None = None
    gender_source_end: int | None = None
    gender_low_confidence: bool = False


@dataclass
class VictimSpec:
    first_name: str | None = "Test"
    last_name: str | None = "Victim"
    gender: str | None = None
    race: str | None = None
    age_text: str | None = None
    age_source: str | None = None
    gender_source: str | None = None
    extraction: VictimExtractionSpec | None = None


@dataclass
class ContactSpec:
    last_name: str = "Cold Case Unit"
    phone: str | None = None


@dataclass
class PhotoSpec:
    filename: str = "photo.jpg"
    content_type: str = "image/jpeg"
    sha256: str = "0" * 64
    storage_path: str | None = None
    is_primary: bool = True


@dataclass
class ExtractionSpec:
    prompt_tier: int  # 1 or 2
    weapon: str | None = None
    weapon_low_confidence: bool = False
    location_type: str | None = None
    location_type_low_confidence: bool = False
    incident_date_text: str | None = None
    address_text: str | None = None
    victim_age_text: str | None = None
    victim_gender_text: str | None = None


@dataclass
class CaseSpec:
    source_case_id: str
    case_name: str
    state: str
    case_type: str = "homicide"
    city: str | None = None
    incident_date: str | None = None  # ISO YYYY-MM-DD
    address: str | None = None
    about_text: str = ""
    latitude: float | None = None
    longitude: float | None = None
    geocode_precision: str | None = None
    source_county_fips: str | None = None
    slug: str | None = None  # defaults to "<source_code>-<source_case_id>" (globally unique)
    victims: list[VictimSpec] = field(default_factory=list)
    contact: ContactSpec | None = None
    photos: list[PhotoSpec] = field(default_factory=list)
    extractions: list[ExtractionSpec] = field(default_factory=list)


@dataclass
class SeededCorpus:
    source_system_id: int
    dataset_version_id: int
    case_ids: dict[str, int]
    _session_factory: sessionmaker[Session]

    def teardown(self) -> None:
        """FK-safe delete everything this corpus inserted."""
        dv = self.dataset_version_id
        with self._session_factory() as s:
            case_filter = (
                "case_id IN (SELECT case_id FROM cold_case.cases " "WHERE dataset_version_id = :dv)"
            )
            for child in (
                "geocoding_job",
                "extraction_job",
                "case_extractions",
                "case_photo",
                "victim_extraction",
                "victim",
                "contact",
            ):
                s.execute(
                    text(f"DELETE FROM cold_case.{child} WHERE {case_filter}"),
                    {"dv": dv},
                )
            s.execute(
                text("DELETE FROM cold_case.cases WHERE dataset_version_id = :dv"),
                {"dv": dv},
            )
            s.execute(
                text("DELETE FROM etl.ingestion_run WHERE dataset_version_id = :dv"),
                {"dv": dv},
            )
            s.execute(
                text("DELETE FROM etl.dataset_version WHERE dataset_version_id = :dv"),
                {"dv": dv},
            )
            s.execute(
                text("DELETE FROM etl.source_system WHERE source_system_id = :ss"),
                {"ss": self.source_system_id},
            )
            s.commit()


class SeedFn(Protocol):
    """Callable yielded by the ``seed`` / ``seeded_corpus`` fixtures."""

    def __call__(
        self,
        source_code: str,
        cases: list[CaseSpec],
        *,
        source_state: str | None = None,
    ) -> SeededCorpus: ...


def seed_corpus(
    session_factory: sessionmaker[Session],
    *,
    source_code: str,
    cases: list[CaseSpec],
    source_state: str | None = None,
) -> SeededCorpus:
    """Insert a source_system + dataset_version + ingestion_run + the given
    cases and their dependent rows. Commits. Returns a SeededCorpus."""
    case_ids: dict[str, int] = {}
    with session_factory() as s:
        source_system_id = s.execute(
            text(
                "INSERT INTO etl.source_system (source_code, source_name) "
                "VALUES (:code, :name) RETURNING source_system_id"
            ),
            {"code": source_code, "name": f"{source_code} (integration-test seed)"},
        ).scalar_one()
        dataset_version_id = s.execute(
            text(
                "INSERT INTO etl.dataset_version "
                "(source_system_id, source_year, source_state, source_label, source_hash, "
                " ingestion_status) "
                "VALUES (:ss, 2026, :source_state, :label, :hash, 'published') "
                "RETURNING dataset_version_id"
            ),
            {
                "ss": source_system_id,
                "source_state": source_state,
                "label": f"{source_code} seed",
                "hash": f"seed-{source_code}",
            },
        ).scalar_one()
        s.execute(
            text(
                "INSERT INTO etl.ingestion_run (dataset_version_id, run_status) "
                "VALUES (:dv, 'succeeded')"
            ),
            {"dv": dataset_version_id},
        )

        for c in cases:
            case_id = s.execute(
                text(
                    "INSERT INTO cold_case.cases "
                    "(dataset_version_id, source_case_id, slug, case_name, "
                    " case_type, state, city, incident_date, address, about_text, "
                    " latitude, longitude, geocode_precision, source_county_fips) "
                    "VALUES "
                    "(:dv, :scid, :slug, :name, :ctype, :state, :city, :date, "
                    " :address, :about, :lat, :lon, :prec, :fips) "
                    "RETURNING case_id"
                ),
                {
                    "dv": dataset_version_id,
                    "scid": c.source_case_id,
                    "slug": c.slug or f"{source_code}-{c.source_case_id}".lower(),
                    "name": c.case_name,
                    "ctype": c.case_type,
                    "state": c.state,
                    "city": c.city,
                    "date": c.incident_date,
                    "address": c.address,
                    "about": c.about_text,
                    "lat": c.latitude,
                    "lon": c.longitude,
                    "prec": c.geocode_precision,
                    "fips": c.source_county_fips,
                },
            ).scalar_one()
            case_ids[c.source_case_id] = case_id

            for ordinal, v in enumerate(c.victims, start=1):
                victim_id = s.execute(
                    text(
                        "INSERT INTO cold_case.victim "
                        "(case_id, first_name, last_name, gender, race, age_text, "
                        " age_source, gender_source) "
                        "VALUES (:cid, :fn, :ln, :g, :r, :age, :asrc, :gsrc) "
                        "RETURNING victim_id"
                    ),
                    {
                        "cid": case_id,
                        "fn": v.first_name,
                        "ln": v.last_name,
                        "g": v.gender,
                        "r": v.race,
                        "age": v.age_text,
                        "asrc": v.age_source,
                        "gsrc": v.gender_source,
                    },
                ).scalar_one()
                if v.extraction is not None:
                    e = v.extraction
                    s.execute(
                        text(
                            "INSERT INTO cold_case.victim_extraction "
                            "(case_id, victim_ordinal, model_id, prompt_hash, "
                            " prompt_tier, victim_id, name_text, "
                            " victim_age_text, victim_age_raw_phrase, "
                            " victim_age_source_start, victim_age_source_end, "
                            " victim_age_low_confidence, "
                            " victim_gender_text, victim_gender_raw_phrase, "
                            " victim_gender_source_start, victim_gender_source_end, "
                            " victim_gender_low_confidence) "
                            "VALUES (:cid, :ord, 'seed-model', 'seed-tier2', 2, "
                            " :vid, :nt, :at, :arp, :ass, :ase, :alc, "
                            " :gt, :grp, :gss, :gse, :glc)"
                        ),
                        {
                            "cid": case_id,
                            "ord": ordinal,
                            "vid": victim_id,
                            "nt": e.name_text,
                            "at": e.age_text,
                            "arp": e.age_raw_phrase,
                            "ass": e.age_source_start,
                            "ase": e.age_source_end,
                            "alc": e.age_low_confidence,
                            "gt": e.gender_text,
                            "grp": e.gender_raw_phrase,
                            "gss": e.gender_source_start,
                            "gse": e.gender_source_end,
                            "glc": e.gender_low_confidence,
                        },
                    )
            if c.contact is not None:
                s.execute(
                    text(
                        "INSERT INTO cold_case.contact (case_id, last_name, phone) "
                        "VALUES (:cid, :ln, :ph)"
                    ),
                    {"cid": case_id, "ln": c.contact.last_name, "ph": c.contact.phone},
                )
            for p in c.photos:
                s.execute(
                    text(
                        "INSERT INTO cold_case.case_photo "
                        "(case_id, filename, content_type, sha256, is_primary, "
                        " storage_path) "
                        "VALUES (:cid, :fn, :ct, :sha, :prim, :sp)"
                    ),
                    {
                        "cid": case_id,
                        "fn": p.filename,
                        "ct": p.content_type,
                        "sha": p.sha256,
                        "prim": p.is_primary,
                        "sp": p.storage_path,
                    },
                )
            for ext in c.extractions:
                s.execute(
                    text(
                        "INSERT INTO cold_case.case_extractions "
                        "(case_id, extractor_version, prompt_hash, model_id, "
                        " prompt_tier, weapon, location_type, "
                        " weapon_low_confidence, location_type_low_confidence, "
                        " incident_date_text, address_text, victim_age_text, "
                        " victim_gender_text) "
                        "VALUES (:cid, 'seed', :ph, 'seed-model', :tier, "
                        " :weapon, :loc, :w_low, :l_low, :idate, :addr, :vage, "
                        " :vg)"
                    ),
                    {
                        "cid": case_id,
                        "ph": f"seed-tier{ext.prompt_tier}",
                        "tier": ext.prompt_tier,
                        "weapon": ext.weapon,
                        "loc": ext.location_type,
                        "w_low": ext.weapon_low_confidence,
                        "l_low": ext.location_type_low_confidence,
                        "idate": ext.incident_date_text,
                        "addr": ext.address_text,
                        "vage": ext.victim_age_text,
                        "vg": ext.victim_gender_text,
                    },
                )
        s.commit()

    return SeededCorpus(
        source_system_id=source_system_id,
        dataset_version_id=dataset_version_id,
        case_ids=case_ids,
        _session_factory=session_factory,
    )
