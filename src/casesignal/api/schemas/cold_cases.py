from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from casesignal.correlation.schemas import CorrelatedCaseSummary


class ColdCaseMapItem(BaseModel):
    case_id: int
    slug: str
    source_case_id: str
    case_name: str
    case_type: str
    incident_date: date | None
    latitude: float
    longitude: float
    state: str
    city: str | None
    victim_primary_name: str | None
    victim_genders: list[str]
    victim_races: list[str]
    geocode_precision: str | None
    source_county_fips: str | None = None

    model_config = ConfigDict(extra="forbid")


class ColdCaseMapClusterItem(BaseModel):
    """One server-aggregated map cluster — a grid cell's centroid + count."""

    latitude: float
    longitude: float
    count: int

    model_config = ConfigDict(extra="forbid")


class ColdCaseMapMeta(BaseModel):
    bbox: tuple[float, float, float, float] | None
    returned: int
    truncated: bool
    total_unfiltered: int

    model_config = ConfigDict(extra="forbid")


class ColdCaseMapResponse(BaseModel):
    """Map payload. `mode` discriminates: at low zoom the server returns
    aggregated `clusters` and `data` is empty; at high zoom it returns
    individual `data` points and `clusters` is empty."""

    mode: Literal["points", "clusters"]
    data: list[ColdCaseMapItem] = []
    clusters: list[ColdCaseMapClusterItem] = []
    meta: ColdCaseMapMeta

    model_config = ConfigDict(extra="forbid")


class SortOrder(str, Enum):
    incident_date_desc = "incident_date_desc"
    incident_date_asc = "incident_date_asc"
    victim_name_asc = "victim_name_asc"
    victim_name_desc = "victim_name_desc"
    source_case_id_asc = "source_case_id_asc"
    source_case_id_desc = "source_case_id_desc"
    case_type_asc = "case_type_asc"
    case_type_desc = "case_type_desc"
    location_asc = "location_asc"
    location_desc = "location_desc"
    state_asc = "state_asc"
    state_desc = "state_desc"


class ColdCaseListItem(BaseModel):
    case_id: int
    slug: str
    source_case_id: str
    case_name: str
    case_type: str
    incident_date: date | None
    city: str | None
    state: str
    victim_primary_name: str | None
    victim_primary_gender: str | None
    victim_primary_age: int | None
    victim_primary_race: str | None
    weapon: str | None
    weapon_low_confidence: bool
    location_type: str | None
    location_type_low_confidence: bool
    geocode_precision: str | None

    model_config = ConfigDict(extra="forbid")


class ColdCaseListMeta(BaseModel):
    total: int
    offset: int
    limit: int
    total_unfiltered: int

    model_config = ConfigDict(extra="forbid")


class ColdCaseListResponse(BaseModel):
    data: list[ColdCaseListItem]
    meta: ColdCaseListMeta

    model_config = ConfigDict(extra="forbid")


class ExtractedField(BaseModel):
    """Per-field extraction state. Four valid (value, low_confidence) tuples:

    (concrete-value, false) — confident classification with resolvable source
                              span. raw_phrase + source_start + source_end
                              populated.
    (concrete-value, true)  — LLM classified but verbatim phrase didn't
                              resolve. raw_phrase MAY be set; offsets NULL.
    ('unknown', false)      — confident "narrative does not specify."
                              raw_phrase + offsets NULL. NOT a failure.
    (None, true)            — LLM API call failed (row-level: both fields
                              return this together).
    """

    value: str | None
    raw_phrase: str | None
    source_start: int | None
    source_end: int | None
    low_confidence: bool

    model_config = ConfigDict(extra="forbid")


class VictimSection(BaseModel):
    victim_id: int
    first_name: str | None
    last_name: str | None
    gender: str | None
    height_text: str | None
    weight_num: int | None
    age_text: str | None
    age_num: int | None
    race: str | None
    eye_color: str | None
    hair_color: str | None
    dob: str | None = None
    dod: str | None = None
    ethnicity: str | None = None
    tribal_affiliation: str | None = None
    identifying_marks: str | None = None
    aliases: str | None = None
    occupation: str | None = None
    age_source: Literal["source", "tier2"] | None = None
    gender_source: Literal["source", "tier2"] | None = None
    race_source: Literal["source", "tier2"] | None = None
    # Per-victim Tier-2 provenance, present ONLY when the corresponding
    # *_source is 'tier2' (i.e. the displayed value came from this extraction).
    # Drives the per-victim reveal-source UI. Spec §5.
    age_extraction: ExtractedField | None = None
    gender_extraction: ExtractedField | None = None

    model_config = ConfigDict(extra="forbid")


class CaseContactSection(BaseModel):
    # Note: detective first_name / last_name are deliberately NOT in this model.
    # Redaction enforced at the API boundary; the full names never leave the server.
    phone: str | None
    email: str | None
    address: str | None

    model_config = ConfigDict(extra="forbid")


class CaseExtractionBlock(BaseModel):
    """Surfaces model_id + extracted_at intentionally — provenance per the
    audit-trail principle, scannable on every detail page.

    Tier-1 fields (weapon, location_type) are always present (may be
    'unknown' or null with low_confidence). Tier-2 fields (incident_date,
    address) are present when an extraction row exists with prompt_tier=2;
    null otherwise (e.g. CSV sources like VA where these fields came from
    structured input). Victim age/gender provenance is per-victim on
    VictimSection.age_extraction / gender_extraction (Phase 2).
    """

    weapon: ExtractedField
    location_type: ExtractedField
    incident_date: ExtractedField | None = None
    address: ExtractedField | None = None
    model_id: str
    extracted_at: datetime

    model_config = ConfigDict(extra="forbid")


class CasePhoto(BaseModel):
    """Per-case photo metadata; the actual bytes are served by
    GET /api/v1/cold-cases/{case_id}/photos/{filename}."""

    filename: str
    content_type: str
    width: int | None
    height: int | None
    alt_text: str | None
    is_primary: bool

    model_config = ConfigDict(extra="forbid")


class CaseDetailResponse(BaseModel):
    case_id: int
    slug: str
    source_case_id: str
    case_name: str
    case_type: str
    incident_date: date | None
    address: str | None
    city: str | None
    state: str
    about_text: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    geocode_precision: str | None
    namus_case_id: str | None = None
    ncmec_case_id: str | None = None
    ncic_case_id: str | None = None
    address_source: Literal["source", "tier2"] | None = None
    incident_date_source: Literal["source", "tier2"] | None = None
    victims: list[VictimSection]
    contact: CaseContactSection | None
    extraction: CaseExtractionBlock | None
    correlations: list[CorrelatedCaseSummary]
    photos: list[CasePhoto]

    model_config = ConfigDict(extra="forbid")


class YearRange(BaseModel):
    min: int | None
    max: int | None

    model_config = ConfigDict(extra="forbid")


class DatasetBlock(BaseModel):
    version: str
    last_ingested: datetime | None

    model_config = ConfigDict(extra="forbid")


class SourceSystemOption(BaseModel):
    """One available source-system filter option."""

    code: str
    name: str

    model_config = ConfigDict(extra="forbid")


class SourceSummaryItem(BaseModel):
    """Per-source aggregate stats for the methodology page."""

    code: str
    name: str
    state: str | None
    case_count: int
    geocoded_count: int
    year_min: int | None
    year_max: int | None

    model_config = ConfigDict(extra="forbid")


class SourcesSummaryResponse(BaseModel):
    data: list[SourceSummaryItem]

    model_config = ConfigDict(extra="forbid")


class FilterOptionsResponse(BaseModel):
    """All distinct values returned alphabetically. Scope: unscoped, all-time
    across the corpus.

    weapons + location_types come from cold_case.case_extractions_current and
    include 'unknown' when present in data; NULL values are filtered out
    (no phantom blank entries from un-extracted rows).

    source_systems lists all source-system codes that have at least one
    case ingested.
    """

    case_types: list[str]
    cities: list[str]
    genders: list[str]
    races: list[str]
    states: list[str]
    weapons: list[str]
    location_types: list[str]
    source_systems: list[SourceSystemOption]
    year_range: YearRange
    dataset: DatasetBlock

    model_config = ConfigDict(extra="forbid")


class FacetCount(BaseModel):
    """One filter value and how many cases carry it."""

    value: str
    count: int

    model_config = ConfigDict(extra="forbid")


class FacetCountsResponse(BaseModel):
    """Per-facet case counts for the filter rail + landing jurisdiction bars.

    Counts are FACETED — each value reflects all *other* active filters but not
    the facet's own selection, so toggling one value in a multi-select doesn't
    zero out its siblings. With no filters this is the corpus-wide total. `gender`
    and `race` are canonicalized + count distinct cases (a case with multiple
    same-value victims counts once); their value strings match the corresponding
    `/filter-options` entries so the rail can key counts by option. `source_system`
    is keyed by source_code (not name). `geocoded`/`total` apply ALL filters.
    """

    case_type: list[FacetCount]
    state: list[FacetCount]
    gender: list[FacetCount]
    race: list[FacetCount]
    precision: list[FacetCount]
    weapon: list[FacetCount]
    location_type: list[FacetCount]
    source_system: list[FacetCount]
    geocoded: int
    total: int

    model_config = ConfigDict(extra="forbid")


class CoverageBucket(BaseModel):
    state: str
    decade: int
    count: int

    model_config = ConfigDict(extra="forbid")


class CoverageHistogramResponse(BaseModel):
    """Per-(state, decade) published-case counts for the coverage heatmap.
    Same published-only gating as the year histogram (no archived leakage)."""

    buckets: list[CoverageBucket]

    model_config = ConfigDict(extra="forbid")


class YearBucket(BaseModel):
    year: int
    count: int

    model_config = ConfigDict(extra="forbid")


class YearHistogramResponse(BaseModel):
    """Per-year case counts (years with >=1 dated case, ascending) plus the
    undated remainder. The frontend buckets these into decades for the deck
    histogram; per-year keeps the endpoint reusable for finer views.
    """

    buckets: list[YearBucket]
    total_dated: int
    undated: int

    model_config = ConfigDict(extra="forbid")
