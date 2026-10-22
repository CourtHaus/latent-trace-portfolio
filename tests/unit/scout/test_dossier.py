from casesignal.scout.dossier import render_dossier
from casesignal.scout.models import (
    Candidate,
    CaseCount,
    Channel,
    Confidence,
    GateResult,
    Gates,
    Level,
    Status,
)
from casesignal.scout.registry import Registry


def _reg() -> Registry:
    reg = Registry({}, [])
    strong = Candidate(
        id="tx",
        level=Level.STATE,
        state="TX",
        index_url="https://tx.gov",
        channel=Channel.WEB,
        agency="Texas Rangers",
        gates=Gates(GateResult.PASS, GateResult.PASS),
        case_count=CaseCount(152, Confidence.EXACT, "totals"),
        plottability=1.0,
        score=0.94,
    )
    weak = Candidate(
        id="zz",
        level=Level.STATE,
        state="ZZ",
        index_url="https://zz.gov",
        channel=Channel.WEB,
        gates=Gates(GateResult.PASS, GateResult.PASS),
        case_count=CaseCount(10, Confidence.VISIBLE, "visible"),
        plottability=0.5,
        score=0.20,
    )
    rej = Candidate(
        id="news",
        level=Level.STATE,
        state="TX",
        index_url="https://news.com",
        channel=Channel.WEB,
        status=Status.REJECTED,
        gates=Gates(GateResult.PASS, GateResult.FAIL, "news aggregator, not first party"),
    )
    for c in (strong, weak, rej):
        reg.upsert(c)
    reg.defer_county("TX", "Loving", 254, "dry streak reached")
    return reg


def test_render_ranks_and_includes_sections() -> None:
    out = render_dossier(_reg(), run_date="2026-07-09")
    assert out.index("tx") < out.index("zz")  # higher score first
    assert "Rejected" in out and "news aggregator" in out
    assert "Loving" in out  # deferred ledger surfaced
    assert "—" not in out  # no em-dashes
