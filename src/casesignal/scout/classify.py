"""Classification contract: the verdict schema a Claude subagent fills, plus the
prompt it is given and the loader/validator/applier the finalize phase uses.

The subagent dispatch itself is performed by Claude Code at run time (a plain
Python process cannot call the Agent tool); this module is the file-interface
around that gap.
"""

from __future__ import annotations

from typing import Any

from casesignal.scout.models import (
    Candidate,
    FieldSpec,
    GateResult,
    Gates,
    Level,
    Location,
    Page,
    Status,
)

_GATE_VALUES = {"pass", "fail", "unknown"}
_LOCATION_VALUES = {"structured", "narrative", "absent"}
_PAGE_VALUES = {"list", "detail"}

VERDICT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["gates"],
    "properties": {
        "gates": {
            "type": "object",
            "required": ["cold_homicide", "official_first_party"],
            "properties": {
                "cold_homicide": {"enum": sorted(_GATE_VALUES)},
                "official_first_party": {"enum": sorted(_GATE_VALUES)},
                "reason": {"type": ["string", "null"]},
            },
        },
        "fields": {"type": "object"},
        "state": {"type": ["string", "null"]},
        "county": {"type": ["string", "null"]},
        "level": {"enum": ["state", "county", None]},
        "agency": {"type": ["string", "null"]},
        "agency_type": {"type": ["string", "null"]},
        "page_type": {"type": ["string", "null"]},
        "needs_js": {"type": ["boolean", "null"]},
        "tls_impersonate_needed": {"type": ["boolean", "null"]},
        "robots": {"type": ["string", "null"]},
        "auth_required": {"type": ["boolean", "null"]},
        "case_type_mix": {"type": "array"},
        "source_id_strategy": {"type": ["string", "null"]},
        "source_id_field": {"type": ["string", "null"]},
        "detail_url_pattern": {"type": ["string", "null"]},
        "plottability_hint": {"type": ["number", "null"]},
    },
}


def build_subagent_prompt(c: Candidate, evidence_paths: list[str]) -> str:
    paths = "\n".join(f"  - {p}" for p in evidence_paths)
    return f"""You are triaging a candidate cold-case data source for a public
cold-HOMICIDE analytics platform. Read ONLY the captured evidence pages below;
do not browse further.

Candidate: {c.id}
Index URL: {c.index_url}
Evidence pages:
{paths}

Apply two HARD gates (pass/fail):
  1. cold_homicide: does this source publish cold/unsolved HOMICIDE case files
     (victim-level), not aggregate incident statistics?
  2. official_first_party: is the publisher the investigating agency itself
     (state bureau/AG/DPS, county sheriff/PD), not a news outlet or aggregator?
If EITHER fails, set that gate to "fail", give a one-sentence reason, and stop.

If both pass, fill the field inventory. For each of victim_name, race, sex, age,
county, city, address, incident_date, case_number, narrative, photo, contact:
  present (bool), location (structured|narrative|absent), page (list|detail),
  and a short example value when present.
  location = HOW the field is encoded (structured field vs prose vs missing).
  page = WHICH fetch it appears on.
Never infer race; only record whether the SOURCE provides it as a field.

Also report: state, county, level, agency, agency_type, page_type, needs_js,
tls_impersonate_needed, robots, auth_required, case_type_mix, source_id_strategy
(stable|case_number|name_plus_date), source_id_field, detail_url_pattern (the URL
template for a case detail page, or null), plottability_hint (0..1).

Emit ONLY a JSON object matching the agreed verdict schema. No prose."""


def verdict_from_json(data: dict[str, Any]) -> dict[str, Any]:
    gates = data.get("gates")
    if not isinstance(gates, dict) or "cold_homicide" not in gates or (
        "official_first_party" not in gates
    ):
        raise ValueError("verdict missing required 'gates.cold_homicide/official_first_party'")
    for key in ("cold_homicide", "official_first_party"):
        if gates[key] not in _GATE_VALUES:
            raise ValueError(f"gate {key!r} has invalid value {gates[key]!r}")
    for name, spec in (data.get("fields") or {}).items():
        loc = spec.get("location", "absent")
        if loc not in _LOCATION_VALUES:
            raise ValueError(f"field {name!r} has invalid location {loc!r}")
        if spec.get("page") is not None and spec["page"] not in _PAGE_VALUES:
            raise ValueError(f"field {name!r} has invalid page {spec['page']!r}")
    return data


def apply_verdict(c: Candidate, verdict: dict[str, Any]) -> None:
    g = verdict["gates"]
    c.gates = Gates(
        cold_homicide=GateResult(g["cold_homicide"]),
        official_first_party=GateResult(g["official_first_party"]),
        reason=g.get("reason"),
    )
    c.fields = {
        name: FieldSpec(
            present=bool(spec.get("present")),
            location=Location(spec.get("location", "absent")),
            page=Page(spec["page"]) if spec.get("page") else None,
            example=spec.get("example"),
            encoding=spec.get("encoding"),
        )
        for name, spec in (verdict.get("fields") or {}).items()
    }
    # Catalog-channel candidates arrive without scope fields; the classifier fills
    # them. Only apply a value the verdict actually carries: an ABSENT key or an
    # explicit null must not clobber an already-discovered value. Use `is not None`
    # (not truthiness) so a legitimate False boolean still applies.
    if verdict.get("state"):
        c.state = verdict["state"]
    if (level := verdict.get("level")) is not None:
        c.level = Level(level)
    for attr, key in (
        ("county", "county"),
        ("agency", "agency"),
        ("agency_type", "agency_type"),
        ("page_type", "page_type"),
        ("needs_js", "needs_js"),
        ("tls_impersonate_needed", "tls_impersonate_needed"),
        ("robots", "robots"),
        ("auth_required", "auth_required"),
        ("source_id_strategy", "source_id_strategy"),
        ("source_id_field", "source_id_field"),
        ("detail_url_pattern", "detail_url_pattern"),
    ):
        value = verdict.get(key)
        if value is not None:
            setattr(c, attr, value)
    c.case_type_mix = list(verdict.get("case_type_mix") or [])
    if verdict.get("plottability_hint") is not None:
        c.plottability = float(verdict["plottability_hint"])

    if (
        c.gates.cold_homicide != GateResult.PASS
        or c.gates.official_first_party != GateResult.PASS
    ):
        c.status = Status.REJECTED
        # Drop any score carried over from a prior finalize: a gate-failed source
        # must not linger in the dossier's ranked section, which includes every
        # candidate whose score is not None.
        c.score = None
        c.score_breakdown = {}
