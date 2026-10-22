"""Registry: the Scout's frontier memory (a single atomic YAML file)."""

from __future__ import annotations

import os
import re
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from casesignal.scout.models import (
    Candidate,
    CaptureInfo,
    CaseCount,
    Channel,
    Confidence,
    FieldSpec,
    GateResult,
    Gates,
    Level,
    Location,
    LocatorKind,
    Page,
    Status,
)

# Lifecycle order for the no-regression rule (higher index = more advanced).
_ORDER = [
    Status.CANDIDATE,
    Status.NEEDS_REVIEW,
    Status.DEFERRED,
    Status.REJECTED,
    Status.ACCEPTED,
    Status.INGESTED,
]
_SOURCE_FILE_RE = re.compile(r"^cold_case_([a-z]{2})\.yaml$")


def covered_states(sources_dir: Path) -> set[str]:
    out: set[str] = set()
    for p in sources_dir.glob("cold_case_*.yaml"):
        m = _SOURCE_FILE_RE.match(p.name)
        if m:
            out.add(m.group(1).upper())
    return out


class Registry:
    def __init__(self, candidates: dict[str, Candidate], deferred: list[dict[str, Any]]) -> None:
        self._candidates = candidates
        self._deferred = deferred

    @classmethod
    def load(cls, path: Path) -> Registry:
        if not path.exists():
            return cls({}, [])
        raw = yaml.safe_load(path.read_text()) or {}
        candidates = {
            cid: _candidate_from_dict(d) for cid, d in (raw.get("candidates") or {}).items()
        }
        return cls(candidates, list(raw.get("deferred") or []))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "candidates": {cid: _candidate_to_dict(c) for cid, c in self._candidates.items()},
            "deferred": self._deferred,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(payload, sort_keys=True))
        os.replace(tmp, path)  # atomic

    def upsert(self, c: Candidate) -> None:
        existing = self._candidates.get(c.id)
        if existing is not None and _ORDER.index(existing.status) > _ORDER.index(c.status):
            c.status = existing.status
        self._candidates[c.id] = c

    def get(self, candidate_id: str) -> Candidate | None:
        return self._candidates.get(candidate_id)

    def all(self) -> list[Candidate]:
        return list(self._candidates.values())

    def by_status(self, status: Status) -> list[Candidate]:
        return [c for c in self._candidates.values() if c.status == status]

    def defer_county(self, state: str, county: str, population_rank: int, reason: str) -> None:
        self._deferred.append(
            {"state": state, "county": county, "population_rank": population_rank, "reason": reason}
        )

    def deferred(self) -> list[dict[str, Any]]:
        return list(self._deferred)


def _candidate_to_dict(c: Candidate) -> dict[str, Any]:
    d = asdict(c)
    # asdict leaves Enums as Enum members under some Python builds; coerce to .value.
    result = _enum_to_value(d)
    assert isinstance(result, dict)
    return result


def _enum_to_value(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _enum_to_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_enum_to_value(v) for v in obj]
    return obj


def _candidate_from_dict(d: dict[str, Any]) -> Candidate:
    fields = {
        k: FieldSpec(
            present=v["present"],
            location=Location(v.get("location", "absent")),
            page=Page(v["page"]) if v.get("page") else None,
            example=v.get("example"),
            encoding=v.get("encoding"),
            coverage=v.get("coverage"),
            locator=v.get("locator"),
            locator_kind=LocatorKind(v["locator_kind"]) if v.get("locator_kind") else None,
        )
        for k, v in (d.get("fields") or {}).items()
    }
    gates = None
    if d.get("gates"):
        g = d["gates"]
        gates = Gates(
            cold_homicide=GateResult(g["cold_homicide"]),
            official_first_party=GateResult(g["official_first_party"]),
            reason=g.get("reason"),
        )
    case_count = None
    if d.get("case_count"):
        cc = d["case_count"]
        case_count = CaseCount(
            value=cc.get("value"),
            confidence=Confidence(cc["confidence"]) if cc.get("confidence") else None,
            basis=cc.get("basis"),
        )
    capture = None
    if d.get("capture"):
        cap = d["capture"]
        capture = CaptureInfo(
            session_id=cap["session_id"],
            shape=cap["shape"],
            # `or` (not a get default) so a hand-edited explicit null still types.
            listing_pages=cap.get("listing_pages") or 0,
            records_captured=cap.get("records_captured") or 0,
            records_total=cap.get("records_total"),
            pagination_kind=cap.get("pagination_kind"),
            pagination_detail=cap.get("pagination_detail"),
            transport=cap.get("transport") or "httpx",
            fetched_at=cap.get("fetched_at"),
            listing_record_count=cap.get("listing_record_count") or 0,
            # `bool(... or default)` for the same reason as the siblings above: a
            # hand-edited explicit null must land on the default rather than typing
            # as None. The defaults are the safe readings -- a capture that does not
            # say it was truncated is read as complete only because the drafter
            # refuses to persist a truncated one at all.
            truncated=bool(cap.get("truncated") or False),
            record_list_identified=bool(
                True if cap.get("record_list_identified") is None else cap["record_list_identified"]
            ),
        )
    return Candidate(
        id=d["id"],
        level=Level(d["level"]),
        state=d["state"],
        index_url=d["index_url"],
        channel=Channel(d["channel"]),
        county=d.get("county"),
        agency=d.get("agency"),
        agency_type=d.get("agency_type"),
        dataset_id=d.get("dataset_id"),
        detail_url_pattern=d.get("detail_url_pattern"),
        page_type=d.get("page_type"),
        needs_js=d.get("needs_js"),
        tls_impersonate_needed=d.get("tls_impersonate_needed"),
        robots=d.get("robots"),
        auth_required=d.get("auth_required"),
        gates=gates,
        case_count=case_count,
        plottability=d.get("plottability"),
        plottability_basis=d.get("plottability_basis"),
        case_type_mix=list(d.get("case_type_mix") or []),
        source_id_strategy=d.get("source_id_strategy"),
        source_id_field=d.get("source_id_field"),
        fields=fields,
        score=d.get("score"),
        score_breakdown=dict(d.get("score_breakdown") or {}),
        evidence_dir=d.get("evidence_dir"),
        status=Status(d.get("status", "candidate")),
        notes=d.get("notes"),
        capture=capture,
    )
