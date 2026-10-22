"""The production walker and fixture replay must reconstruct the same records."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pytest
from bs4 import BeautifulSoup

from casesignal.drafter import runtime
from casesignal.etl.services.bs_helpers import attr_str
from casesignal.scout.models import Candidate, Channel, FieldSpec, Level, Page
from tests.unit.drafter import test_shape_json as feeds

INDEX = "https://new-agency.invalid/list"
SECOND = "https://new-agency.invalid/archive/page2"
PAGES = {
    INDEX: '<a class="case" href="/cases/1">Ann</a><a class="case" href="/cases/2">Bob</a><a class="next" href="/archive/page2">Next</a>',
    SECOND: '<a class="case" href="case3">Cal</a>',
    "https://new-agency.invalid/cases/1": "34",
    "https://new-agency.invalid/cases/2": "45",
    "https://new-agency.invalid/archive/case3": "56",
}


class Client:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get(self, url: str) -> runtime.ReplayResponse:
        self.requested.append(url)
        return runtime.ReplayResponse(PAGES[url].encode(), 200)


def spec() -> dict[str, Any]:
    candidate = Candidate(
        id="test",
        state="XX",
        level=Level.STATE,
        channel=Channel.WEB,
        index_url=INDEX,
        detail_url_pattern="https://new-agency.invalid/cases/{id}",
        fields={"age": FieldSpec(present=True, page=Page.DETAIL)},
    )
    return runtime.source_spec(candidate, "html", "httpx")


def parse_records(html: str, *, base_url: str) -> list[dict[str, Any]]:
    return [
        {"victim_name": a.get_text(), "source_url": urljoin(base_url, attr_str(a, "href"))}
        for a in BeautifulSoup(html, "html.parser").select("a.case")
    ]


def parse_detail(html: str, *, url: str) -> dict[str, Any]:
    return {"victim_age": html, "detail_url": url, "victim_name": None}


def capture(root: Path) -> Path:
    held, result = runtime.capture_source(spec(), Client(), root, detail_sample=2)
    fixtures = root / "fixtures"
    (fixtures / "capture.json").write_text(
        json.dumps(
            {
                "version": 1,
                "fixtures": [asdict(f) for f in held.fixtures],
                "detail_sample": len(result.detail_paths),
            }
        )
    )
    return fixtures


def test_production_walks_all_pages_and_all_details() -> None:
    client = Client()
    corpus = runtime.collect(spec(), client, parse_records, parse_detail)
    assert set(client.requested) == set(PAGES)
    assert [r["victim_age"] for r in corpus.records.values()] == ["34", "45", "56"]
    assert [r["victim_name"] for r in corpus.records.values()] == ["Ann", "Bob", "Cal"]
    assert (
        corpus.records["listing_2.html#0"]["source_url"]
        == "https://new-agency.invalid/archive/case3"
    )
    assert all("victim_age" not in r for r in corpus.listings)


def test_replay_joins_sampled_details_and_preserves_capture_keys(tmp_path: Path) -> None:
    root = capture(tmp_path)
    manifest = json.loads((root / "capture.json").read_text())
    entry = next(f for f in manifest["fixtures"] if f["path"] == "listing_2.html")
    (root / entry["path"]).rename(root / "listing_9.html")
    entry["path"] = "listing_9.html"
    (root / "capture.json").write_text(json.dumps(manifest))
    corpus = runtime.replay(root, spec(), parse_records, parse_detail)
    assert len(corpus.records) == 3
    assert len(corpus.details) == 2
    assert corpus.records["listing_1.html#0"]["victim_age"] == "34"
    assert corpus.records["listing_9.html#0"]["victim_age"] == "56"
    assert "victim_age" not in corpus.records["listing_1.html#1"]


def test_replay_refuses_changed_bytes_and_unrecorded_requests(tmp_path: Path) -> None:
    root = capture(tmp_path)
    client = runtime.ReplayClient(root)
    with pytest.raises(ValueError, match="uncaptured"):
        client.get("https://new-agency.invalid/not-captured")
    (root / "listing_1.html").write_text("changed")
    with pytest.raises(ValueError, match="digest mismatch"):
        client.get(INDEX)


def test_runtime_client_preserves_new_host_and_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    options: dict[str, Any] = {}
    monkeypatch.setattr(runtime, "PoliteHTTPClient", lambda **kwargs: options.update(kwargs))
    runtime.make_client(dict(spec(), transport="curl_cffi"), 1.5)
    assert options == {
        "allowed_hosts": {"new-agency.invalid"},
        "bypass_robots_hosts": frozenset(),
        "tls_impersonate": True,
        "rate_limit_seconds": 1.5,
    }


@pytest.mark.parametrize("channel", ["socrata", "arcgis", "embedded"])
def test_runtime_uses_json_feed_walkers(channel: str) -> None:
    if channel == "socrata":
        candidate = feeds._socrata_candidate()
        pages = {feeds._soda(1000, 0): feeds._rows(1, 2)}
    elif channel == "arcgis":
        candidate = feeds._arcgis_candidate()
        pages = {feeds._arc(1000, 0): feeds._features(1, 2, more=False)}
    else:
        candidate = feeds._embedded_candidate()
        pages = {candidate.index_url: feeds._rows(1, 2)}

    def parse(text: str, *, base_url: str) -> list[dict[str, Any]]:
        data = json.loads(text)
        if isinstance(data, dict):
            return [f["attributes"] for f in data["features"]]
        return list(data)

    client = feeds.FakeClient(pages)
    corpus = runtime.collect(
        runtime.source_spec(candidate, "json", "httpx"), client, parse, parse_detail
    )
    assert len(corpus.records) == 2
    assert set(client.requested) == set(pages)
