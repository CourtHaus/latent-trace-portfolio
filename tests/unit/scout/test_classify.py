import json
from pathlib import Path

import pytest

from casesignal.scout.classify import apply_verdict, verdict_from_json
from casesignal.scout.models import (
    Candidate,
    Channel,
    GateResult,
    Level,
    Location,
    Status,
)


def _cand() -> Candidate:
    return Candidate(id="tx_dps_rangers", level=Level.STATE, state="TX",
                     index_url="https://dps.texas.gov/apps/coldCase/", channel=Channel.WEB)


def test_verdict_rejects_missing_gates() -> None:
    with pytest.raises(ValueError):
        verdict_from_json({"fields": {}})


def test_apply_verdict_sets_gates_and_fields() -> None:
    data = json.loads(Path("tests/fixtures/scout/verdicts/tx_dps_rangers.json").read_text())
    c = _cand()
    apply_verdict(c, verdict_from_json(data))
    assert c.gates is not None
    assert c.gates.cold_homicide == GateResult.PASS
    assert c.agency_type == "dps"
    assert c.fields["victim_name"].location == Location.STRUCTURED
    assert c.status == Status.CANDIDATE  # both gates passed -> still scorable


def test_apply_verdict_gate_fail_rejects() -> None:
    data = {"gates": {"cold_homicide": "fail", "official_first_party": "pass",
                      "reason": "aggregate incident data, not case files"},
            "fields": {}}
    c = _cand()
    apply_verdict(c, verdict_from_json(data))
    assert c.status == Status.REJECTED
    assert c.gates is not None
    assert c.gates.reason is not None
    assert "aggregate" in c.gates.reason


def test_apply_verdict_gate_fail_clears_stale_score() -> None:
    # A candidate scored on a prior finalize, now re-applied with a failing gate:
    # the old score must be dropped so it does not linger in the dossier's ranked
    # section (which includes every candidate whose score is not None).
    c = _cand()
    c.score = 0.87
    c.score_breakdown = {"count": 0.9}
    data = {"gates": {"cold_homicide": "fail", "official_first_party": "pass",
                      "reason": "news aggregator, not first party"},
            "fields": {}}
    apply_verdict(c, verdict_from_json(data))
    assert c.status == Status.REJECTED
    assert c.score is None
    assert c.score_breakdown == {}


def test_apply_verdict_explicit_null_does_not_clobber() -> None:
    data = {"gates": {"cold_homicide": "pass", "official_first_party": "pass",
                      "reason": None},
            "county": None, "fields": {}}
    c = _cand()
    c.county = "Harris County"
    apply_verdict(c, verdict_from_json(data))
    assert c.county == "Harris County"  # explicit null must not overwrite


def test_apply_verdict_explicit_false_still_applies() -> None:
    data = {"gates": {"cold_homicide": "pass", "official_first_party": "pass",
                      "reason": None},
            "needs_js": False, "fields": {}}
    c = _cand()
    c.needs_js = True
    apply_verdict(c, verdict_from_json(data))
    assert c.needs_js is False  # legitimate False must apply, not be treated as absent


def test_apply_verdict_sets_detail_url_pattern() -> None:
    data = {"gates": {"cold_homicide": "pass", "official_first_party": "pass",
                      "reason": None},
            "detail_url_pattern": "https://dps.texas.gov/apps/coldCase/{id}",
            "fields": {}}
    c = _cand()
    apply_verdict(c, verdict_from_json(data))
    assert c.detail_url_pattern == "https://dps.texas.gov/apps/coldCase/{id}"


def test_verdict_rejects_invalid_gate_value() -> None:
    with pytest.raises(ValueError):
        verdict_from_json({"gates": {"cold_homicide": "maybe",
                                     "official_first_party": "pass"},
                           "fields": {}})


def test_verdict_rejects_invalid_field_location() -> None:
    with pytest.raises(ValueError):
        verdict_from_json({"gates": {"cold_homicide": "pass",
                                     "official_first_party": "pass"},
                           "fields": {"victim_name": {"present": True,
                                                      "location": "elsewhere"}}})


def test_verdict_rejects_invalid_field_page() -> None:
    with pytest.raises(ValueError):
        verdict_from_json({"gates": {"cold_homicide": "pass",
                                     "official_first_party": "pass"},
                           "fields": {"victim_name": {"present": True,
                                                      "location": "structured",
                                                      "page": "sidebar"}}})
