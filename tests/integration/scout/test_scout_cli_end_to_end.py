"""End-to-end: discover (fixture search) -> verdict -> finalize -> ranked dossier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from casesignal.scout import cli, run
from casesignal.scout.models import (
    Candidate,
    CaseCount,
    Channel,
    Confidence,
    Level,
    Status,
)
from casesignal.scout.registry import Registry

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _search_fn_from_fixture(_queries: list[str]) -> list[dict[str, Any]]:
    lines = Path("tests/fixtures/scout/websearch_results.jsonl").read_text().splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def _passing_verdict() -> dict[str, Any]:
    return {
        "gates": {
            "cold_homicide": "pass",
            "official_first_party": "pass",
            "reason": None,
        },
        "state": "TX",
        "level": "state",
        "agency": "Texas Rangers",
        "agency_type": "dps",
        "case_type_mix": ["homicide"],
        "plottability_hint": 1.0,
        "fields": {"county": {"present": True, "location": "structured", "page": "list"}},
    }


def test_discover_then_finalize_produces_ranked_dossier(tmp_path: Path) -> None:
    reg_path = tmp_path / "registry.yaml"
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "cold_case_ok.yaml").write_text("x: 1\n")  # OK already covered

    # No catalog client in this test (catalog channel returns nothing).
    worklist = run.discover(
        scope=run.Scope(tier="state"),
        registry_path=reg_path,
        sources_dir=sources_dir,
        out_dir=tmp_path,
        search_fn=_search_fn_from_fixture,
        catalog_client=None,
    )
    assert worklist.exists()
    reg = Registry.load(reg_path)
    cand = next(c for c in reg.all() if "dps.texas.gov" in c.index_url)
    assert cand.evidence_dir is not None  # discover set the evidence dir

    # The worklist line carries the slugged verdict filename for the SP2 handoff.
    row = json.loads(worklist.read_text().splitlines()[0])
    assert row["verdict_filename"] == f"{run.candidate_slug(cand.id)}.json"
    assert "/" not in row["verdict_filename"]

    # Simulate the classification gap: drop a passing verdict for the candidate.
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    (verdicts / f"{run.candidate_slug(cand.id)}.json").write_text(
        json.dumps(
            {
                "gates": {
                    "cold_homicide": "pass",
                    "official_first_party": "pass",
                    "reason": None,
                },
                "state": "TX",
                "level": "state",
                "agency": "Texas Rangers",
                "agency_type": "dps",
                "case_type_mix": ["homicide"],
                "plottability_hint": 1.0,
                "fields": {
                    "county": {"present": True, "location": "structured", "page": "list"}
                },
            }
        )
    )

    dossier = run.finalize(
        registry_path=reg_path,
        verdicts_dir=verdicts,
        run_date="2026-07-09",
        out_dir=tmp_path,
    )
    text = dossier.read_text()
    assert "dps.texas.gov" in text
    reg2 = Registry.load(reg_path)
    scored = reg2.get(cand.id)
    assert scored is not None
    assert scored.score is not None  # gates passed -> scored


def test_finalize_reapplies_a_late_verdict_after_needs_review(tmp_path: Path) -> None:
    """A CANDIDATE with no verdict becomes NEEDS_REVIEW; when the verdict is
    dropped on a LATER finalize it must still be applied and scored (regression
    guard for the status-filter re-run trap)."""
    reg_path = tmp_path / "registry.yaml"
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    cand = Candidate(
        id="dps.texas.gov/apps",
        level=Level.STATE,
        state="TX",
        index_url="https://dps.texas.gov/apps/coldCase/",
        channel=Channel.WEB,
    )
    reg = Registry.load(reg_path)
    reg.upsert(cand)
    reg.save(reg_path)

    # First finalize, no verdict on disk yet -> NEEDS_REVIEW.
    run.finalize(reg_path, verdicts, "2026-07-09", tmp_path)
    mid = Registry.load(reg_path).get(cand.id)
    assert mid is not None
    assert mid.status == Status.NEEDS_REVIEW
    assert mid.score is None

    # Verdict finally arrives; a second finalize must pick it up.
    (verdicts / f"{run.candidate_slug(cand.id)}.json").write_text(json.dumps(_passing_verdict()))
    run.finalize(reg_path, verdicts, "2026-07-10", tmp_path)
    after = Registry.load(reg_path).get(cand.id)
    assert after is not None
    assert after.gates is not None  # verdict applied
    assert after.score is not None  # gates passed -> scored


def test_finalize_reset_rejected_when_reapplied_verdict_passes(tmp_path: Path) -> None:
    """A previously REJECTED candidate whose newly dropped verdict PASSES both
    gates must be reset to CANDIDATE, then scored (not skipped as a stale reject)."""
    reg_path = tmp_path / "registry.yaml"
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    cand = Candidate(
        id="dps.texas.gov/apps",
        level=Level.STATE,
        state="TX",
        index_url="https://dps.texas.gov/apps/coldCase/",
        channel=Channel.WEB,
        status=Status.REJECTED,
    )
    reg = Registry.load(reg_path)
    reg.upsert(cand)
    reg.save(reg_path)

    # Drop a passing verdict at the candidate's verdict filename, no recheck.
    (verdicts / f"{run.candidate_slug(cand.id)}.json").write_text(json.dumps(_passing_verdict()))
    run.finalize(reg_path, verdicts, "2026-07-09", tmp_path)

    after = Registry.load(reg_path).get(cand.id)
    assert after is not None
    assert after.status != Status.REJECTED  # stale reject cleared
    assert after.score is not None  # gates passed -> scored, not skipped


def test_main_recheck_flips_and_persists_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cli.main('recheck rejected') re-queues a REJECTED candidate and persists it."""
    monkeypatch.chdir(tmp_path)
    reg_path = tmp_path / "data" / "scout" / "registry.yaml"
    cand = Candidate(
        id="example.gov/cases",
        level=Level.STATE,
        state="TX",
        index_url="https://example.gov/cases",
        channel=Channel.WEB,
        status=Status.REJECTED,
    )
    reg = Registry.load(reg_path)
    reg.upsert(cand)
    reg.save(reg_path)

    rc = cli.main(["recheck", "rejected"])
    assert rc == 0
    persisted = Registry.load(reg_path).get(cand.id)
    assert persisted is not None
    assert persisted.status == Status.CANDIDATE


def test_main_discover_writes_worklist_catalog_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare cli.main('discover --tier state') drives the catalog channel
    (search_fn returns [], so the web-search gap is empty), writes a NON-EMPTY
    worklist under data/scout, and returns 0 without touching the network. The
    stubbed fetchers prove the catalog channel is wired through the CLI."""
    monkeypatch.chdir(tmp_path)

    fixtures = _REPO_ROOT / "tests" / "fixtures" / "scout"
    socrata_payload = json.loads((fixtures / "socrata_catalog.json").read_text())
    arcgis_payload = json.loads((fixtures / "arcgis_hub.json").read_text())
    # Stub the fetchers in run.py's namespace so no real HTTP happens; the client
    # is still constructed (cheap) and passed through, exercising the CLI wiring.
    monkeypatch.setattr(run, "fetch_socrata", lambda _client, _q: socrata_payload)
    monkeypatch.setattr(run, "fetch_arcgis", lambda _client, _q: arcgis_payload)

    rc = cli.main(["discover", "--tier", "state"])
    assert rc == 0
    worklist = tmp_path / "data" / "scout" / "worklist.jsonl"
    assert worklist.exists()
    lines = [x for x in worklist.read_text().splitlines() if x.strip()]
    assert lines  # catalog channel produced candidates -> worklist is non-empty


def test_discover_county_tier_is_a_no_op_and_skips_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """County-tier discovery is not implemented (Tier B): it must generate an
    empty worklist and NOT run the catalog channel, even though a client is
    supplied, so 'no candidates generated' is actually true."""
    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("catalog channel must not run for county-tier discovery")

    monkeypatch.setattr(run, "fetch_socrata", _boom)
    monkeypatch.setattr(run, "fetch_arcgis", _boom)

    worklist = run.discover(
        scope=run.Scope(state="TX", counties=True),
        registry_path=tmp_path / "registry.yaml",
        sources_dir=tmp_path,
        out_dir=tmp_path,
        search_fn=lambda _q: [],
        catalog_client=object(),  # non-None; must still be skipped
    )
    assert worklist.exists()
    assert worklist.read_text().strip() == ""  # empty: nothing generated


def _seed_scored_candidate(
    reg_path: Path, tmp_path: Path, cid: str, count: CaseCount
) -> Candidate:
    listing_dir = tmp_path / "evidence" / run.candidate_slug(cid)
    listing_dir.mkdir(parents=True, exist_ok=True)
    (listing_dir / "listing.html").write_text('<div class="case"></div>' * 25)
    cand = Candidate(
        id=cid,
        level=Level.STATE,
        state="TX",
        index_url=f"https://{cid}",
        channel=Channel.WEB,
        case_count=count,
        evidence_dir=str(listing_dir),
    )
    reg = Registry.load(reg_path)
    reg.upsert(cand)
    reg.save(reg_path)
    return cand


def test_finalize_does_not_promote_a_visible_count_to_exact(tmp_path: Path) -> None:
    """Re-finalize must re-derive a VISIBLE/PROBED count fresh from the listing,
    never feed it back as api_count (which would stamp it EXACT and drop damping).
    A genuine catalog EXACT count is preserved."""
    reg_path = tmp_path / "registry.yaml"
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()

    visible = _seed_scored_candidate(
        reg_path, tmp_path, "visible.gov/cases",
        CaseCount(value=25, confidence=Confidence.VISIBLE, basis="prior scrape"),
    )
    exact = _seed_scored_candidate(
        reg_path, tmp_path, "exact.gov/cases",
        CaseCount(value=80, confidence=Confidence.EXACT, basis="catalog api"),
    )
    for c in (visible, exact):
        (verdicts / f"{run.candidate_slug(c.id)}.json").write_text(
            json.dumps(_passing_verdict())
        )

    run.finalize(reg_path, verdicts, "2026-07-09", tmp_path)
    reg = Registry.load(reg_path)

    v = reg.get(visible.id)
    assert v is not None and v.case_count is not None
    assert v.case_count.confidence == Confidence.VISIBLE  # re-estimated, not promoted
    assert v.case_count.value == 25

    e = reg.get(exact.id)
    assert e is not None and e.case_count is not None
    assert e.case_count.confidence == Confidence.EXACT  # genuine catalog count preserved
    assert e.case_count.value == 80
