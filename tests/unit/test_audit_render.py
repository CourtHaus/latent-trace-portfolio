from tools.audit.model import AuditContext, Finding, Layer, Rule, Severity
from tools.audit.render import render_text


def _ctx() -> AuditContext:
    return AuditContext(
        source="cold_case_fl_fdle", source_code="FDLE_FL", state="FL",
        dataset_version_id=1199, raw_table="raw_cold_case.cold_case_fl_fdle_dv1199",
        total_cases=681,
    )


def _rule(rid: str, sev: Severity, browser: bool = False) -> Rule:
    return Rule(rid, f"title {rid}", sev, Layer.L1_RAW, browser,
                run=lambda s, c: Finding(0, [], ""))


def test_render_summary_counts_and_pass_marks() -> None:
    ctx = _ctx()
    results = [
        (_rule("R1", Severity.HIGH), Finding(5, [1, 2, 3, 4, 5], "trapped")),
        (_rule("R9", Severity.CRITICAL), Finding(0, [], "ok")),
    ]
    out = render_text(ctx, results)
    assert "cold_case_fl_fdle" in out
    assert "681" in out
    assert "[R1]" in out
    assert "trapped" in out
    assert "R9" in out and "✓" in out  # checkmark for passed rule


def test_render_worklist_section() -> None:
    ctx = _ctx()
    rule = _rule("R1", Severity.HIGH, browser=True)
    finding = Finding(
        1, [48249], "trapped",
        verify_items=[{"case_id": 48249, "search": "Daniluk",
                       "question": "Narrative field blank?"}],
    )
    out = render_text(ctx, [(rule, finding)])
    assert "BROWSER VERIFICATION WORKLIST" in out
    assert "Daniluk" in out
    assert "Narrative field blank?" in out
