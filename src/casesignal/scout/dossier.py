"""Render the human-reviewable dossier markdown from the registry."""

from __future__ import annotations

from casesignal.scout.models import Candidate, GateResult, Location, Status
from casesignal.scout.registry import Registry


def _field_summary(c: Candidate) -> str:
    struct = sorted(
        n for n, f in c.fields.items() if f.present and f.location == Location.STRUCTURED
    )
    narr = sorted(n for n, f in c.fields.items() if f.present and f.location == Location.NARRATIVE)
    return f"structured: {', '.join(struct) or 'none'}; narrative: {', '.join(narr) or 'none'}"


def _entry(c: Candidate) -> str:
    cc = c.case_count
    if cc and cc.value is not None:
        conf = cc.confidence.value if cc.confidence else "unknown"
        count = f"{cc.value} ({conf})"
    else:
        count = "unknown"
    gates = "pass" if c.gates and c.gates.cold_homicide == GateResult.PASS else "?"
    score = c.score if c.score is not None else 0.0
    return (
        f"### {score:.2f}  {c.id}\n"
        f"- Agency: {c.agency or 'unknown'} ({c.state})\n"
        f"- URL: {c.index_url}\n"
        f"- Gates: cold_homicide={gates}, official_first_party="
        f"{c.gates.official_first_party.value if c.gates else '?'}\n"
        f"- Cases: {count}; plottability: "
        f"{c.plottability if c.plottability is not None else '?'}\n"
        f"- Fields: {_field_summary(c)}\n"
        f"- Evidence: {c.evidence_dir or '(none)'}\n"
    )


def render_dossier(reg: Registry, run_date: str) -> str:
    scored = [c for c in reg.all() if c.score is not None]
    scored.sort(key=lambda c: c.score or 0.0, reverse=True)
    rejected = reg.by_status(Status.REJECTED)

    lines = [f"# Source Scout dossier {run_date}", ""]
    lines.append(f"Ranked candidates: {len(scored)}. Review and mark accept, reject, or defer.")
    lines.append("")
    for c in scored:
        lines.append(_entry(c))

    lines.append("## Rejected (auditable)")
    lines.append("")
    for c in rejected:
        reason = c.gates.reason if c.gates and c.gates.reason else "no reason recorded"
        lines.append(f"- {c.id} ({c.index_url}): {reason}")
    lines.append("")

    deferred = reg.deferred()
    lines.append("## Deferred counties (not searched, revisitable)")
    lines.append("")
    for d in deferred:
        lines.append(
            f"- {d['county']} County, {d['state']} (pop rank {d['population_rank']}): {d['reason']}"
        )
    return "\n".join(lines) + "\n"
