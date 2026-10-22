from typing import Any

from casesignal.scout.models import (
    Candidate,
    CaseCount,
    Channel,
    Confidence,
    FieldSpec,
    GateResult,
    Gates,
    Level,
    Location,
)
from casesignal.scout.score import score_candidate


def _c(**kw: Any) -> Candidate:
    base: dict[str, Any] = dict(
        id="x",
        level=Level.STATE,
        state="TX",
        index_url="https://x.gov",
        channel=Channel.WEB,
    )
    base.update(kw)
    return Candidate(**base)


def test_gate_fail_never_scores() -> None:
    c = _c(gates=Gates(cold_homicide=GateResult.FAIL, official_first_party=GateResult.PASS))
    assert score_candidate(c) == (None, {})


def test_visible_confidence_is_damped_below_exact() -> None:
    passed = Gates(cold_homicide=GateResult.PASS, official_first_party=GateResult.PASS)
    hi = _c(gates=passed, plottability=1.0, case_count=CaseCount(150, Confidence.EXACT, "x"))
    lo = _c(gates=passed, plottability=1.0, case_count=CaseCount(150, Confidence.VISIBLE, "x"))
    hi_score = score_candidate(hi)[0]
    lo_score = score_candidate(lo)[0]
    assert hi_score is not None and lo_score is not None
    assert hi_score > lo_score


def test_structured_core_fields_raise_score() -> None:
    passed = Gates(cold_homicide=GateResult.PASS, official_first_party=GateResult.PASS)
    struct = {
        n: FieldSpec(present=True, location=Location.STRUCTURED)
        for n in ("victim_name", "incident_date", "county", "race", "sex")
    }
    rich = _c(
        gates=passed,
        plottability=1.0,
        case_count=CaseCount(150, Confidence.EXACT, "x"),
        fields=struct,
    )
    bare = _c(
        gates=passed,
        plottability=1.0,
        case_count=CaseCount(150, Confidence.EXACT, "x"),
        fields={},
    )
    rich_score = score_candidate(rich)[0]
    bare_score = score_candidate(bare)[0]
    assert rich_score is not None and bare_score is not None
    assert rich_score > bare_score
