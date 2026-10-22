from __future__ import annotations

from tools.audit.model import AuditContext, Finding, Rule, Severity

_SAMPLE_CAP = 10
_PORTAL = "https://web.fdle.state.fl.us/unsolvedcases/public/"


def render_text(
    ctx: AuditContext,
    results: list[tuple[Rule, Finding]],
    *,
    verbose: bool = False,
) -> str:
    lines: list[str] = []
    lines.append(
        f"COLD-CASE INGESTION AUDIT - {ctx.source} "
        f"(dv{ctx.dataset_version_id}, {ctx.total_cases} cases)"
    )
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    by_sev: dict[Severity, list[str]] = {s: [] for s in Severity}
    for rule, finding in results:
        tag = rule.id if finding.has_findings else f"{rule.id}✓"
        by_sev[rule.severity].append(tag)
    for sev in sorted(Severity, reverse=True):
        tags = by_sev[sev]
        if tags:
            lines.append(f"  {sev.label:<9} {len(tags):>2}   ({', '.join(tags)})")
    lines.append("  ✓ = passed (0 findings)")
    lines.append("")

    # Findings by severity (high to low), only rules with findings
    for sev in sorted(Severity, reverse=True):
        section = [(r, f) for r, f in results if r.severity is sev and f.has_findings]
        if not section:
            continue
        lines.append(f"-- {sev.label} " + "-" * (40 - len(sev.label)))
        for rule, finding in section:
            lines.append(f"[{rule.id}] {rule.title} - {finding.detail}")
            ids = finding.case_ids if verbose else finding.case_ids[:_SAMPLE_CAP]
            if ids:
                more = "" if verbose or len(finding.case_ids) <= _SAMPLE_CAP \
                    else f" (+{len(finding.case_ids) - _SAMPLE_CAP} more)"
                lines.append("     case_ids: " + ", ".join(str(i) for i in ids) + more)
            if rule.verify_in_browser and finding.verify_items:
                lines.append(f"     -> see Browser Worklist [{rule.id}]")
        lines.append("")

    # Passed rules, terse
    passed = [r for r, f in results if not f.has_findings]
    if passed:
        lines.append("PASSED")
        for rule in passed:
            lines.append(f"  ✓ [{rule.id}] {rule.title}")
        lines.append("")

    # Worklist
    worklist = [(r, f) for r, f in results if r.verify_in_browser and f.verify_items]
    if worklist:
        lines.append("BROWSER VERIFICATION WORKLIST")
        lines.append(f"Portal: {_PORTAL}")
        lines.append("")
        for rule, finding in worklist:
            lines.append(f"[{rule.id}] {rule.title}")
            for item in finding.verify_items:
                cid = item.get("case_id")
                search = item.get("search", "")
                question = item.get("question", "")
                lines.append(f"    - {cid}  search \"{search}\"  -> {question}")
            lines.append("")

    return "\n".join(lines)
