"""Contract models for the Source Scout (the SP1->SP2 field-inventory schema)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse


class Level(str, Enum):
    STATE = "state"
    COUNTY = "county"


class Status(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    INGESTED = "ingested"
    NEEDS_REVIEW = "needs_review"


class GateResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class Location(str, Enum):
    STRUCTURED = "structured"
    NARRATIVE = "narrative"
    ABSENT = "absent"


class Page(str, Enum):
    LIST = "list"
    DETAIL = "detail"


class Confidence(str, Enum):
    EXACT = "exact"
    PROBED = "probed"
    VISIBLE = "visible"


class Channel(str, Enum):
    WEB = "web"
    SOCRATA = "socrata"
    ARCGIS = "arcgis"


class LocatorKind(str, Enum):
    """How a FieldSpec's locator addresses its value in a captured record."""

    CSS = "css"
    LABEL = "label"
    JSON_PATH = "json_path"


@dataclass
class FieldSpec:
    present: bool
    location: Location = Location.ABSENT
    page: Page | None = None
    example: str | None = None
    encoding: str | None = None
    # Measured by the drafter's inventory pass; None until a capture has run.
    coverage: float | None = None  # fraction of captured records carrying the field
    locator: str | None = None  # CSS selector, label pattern, or JSON path
    locator_kind: LocatorKind | None = None


@dataclass
class CaptureInfo:
    """What a capture run actually pulled down, for the drafter to build on."""

    session_id: str
    shape: str  # html | socrata | arcgis | embedded_json
    listing_pages: int = 0
    records_captured: int = 0
    records_total: int | None = None  # None when unknown; equal to captured = census
    pagination_kind: str | None = None
    pagination_detail: str | None = None
    transport: str = "httpx"
    fetched_at: str | None = None
    listing_record_count: int = 0  # records seen across the whole listing corpus
    # Appended last with defaults, as listing_record_count was, so every existing
    # construction keeps binding. Both carry a capture's own verdict on itself:
    # `truncated` says the walk stopped while the source was still offering more,
    # and `record_list_identified` says the rows measured are the ones the source
    # designates as its records. `records_total is None` cannot express either --
    # it is the consequence of both, and of several innocent causes besides -- so
    # without these two a persisted capture cannot say why its total is unknown.
    truncated: bool = False
    record_list_identified: bool = True


@dataclass
class CaseCount:
    value: int | None = None
    confidence: Confidence | None = None
    basis: str | None = None


@dataclass
class Gates:
    cold_homicide: GateResult = GateResult.UNKNOWN
    official_first_party: GateResult = GateResult.UNKNOWN
    reason: str | None = None


@dataclass
class Candidate:
    id: str
    level: Level
    state: str
    index_url: str
    channel: Channel
    county: str | None = None
    agency: str | None = None
    agency_type: str | None = None
    dataset_id: str | None = None
    detail_url_pattern: str | None = None
    page_type: str | None = None
    needs_js: bool | None = None
    tls_impersonate_needed: bool | None = None
    robots: str | None = None
    auth_required: bool | None = None
    gates: Gates | None = None
    case_count: CaseCount | None = None
    plottability: float | None = None
    plottability_basis: str | None = None
    case_type_mix: list[str] = field(default_factory=list)
    source_id_strategy: str | None = None
    source_id_field: str | None = None
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    score: float | None = None
    score_breakdown: dict[str, float] = field(default_factory=dict)
    evidence_dir: str | None = None
    status: Status = Status.CANDIDATE
    notes: str | None = None
    capture: CaptureInfo | None = None


def dedup_key(channel: Channel, dataset_id: str | None, index_url: str) -> str:
    """Stable identity key. Dataset id when present, else host + first path segment.

    Host alone is too coarse (Socrata hosts hundreds of datasets; state portals
    host many agencies), so we anchor on host + the first non-empty path segment.
    Query string and fragment are ignored so ?area=A and ?area=B collapse.
    """
    if dataset_id:
        return dataset_id
    parsed = urlparse(index_url)
    host = (parsed.hostname or "").lower()
    segments = [s for s in parsed.path.split("/") if s]
    prefix = f"/{segments[0]}" if segments else ""
    return f"{host}{prefix}"
