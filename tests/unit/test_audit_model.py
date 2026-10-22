from tools.audit.model import Finding, Layer, Rule, Severity


def test_finding_defaults_and_truthiness() -> None:
    empty = Finding(count=0, case_ids=[], detail="ok")
    assert not empty.has_findings
    hit = Finding(count=2, case_ids=[1, 2], detail="bad")
    assert hit.has_findings


def test_rule_carries_metadata() -> None:
    rule = Rule(
        id="R1",
        title="example",
        severity=Severity.HIGH,
        layer=Layer.L1_RAW,
        verify_in_browser=True,
        run=lambda session, ctx: Finding(0, [], "ok"),
    )
    assert rule.id == "R1"
    assert rule.severity is Severity.HIGH
    assert rule.layer is Layer.L1_RAW
    assert rule.verify_in_browser is True
