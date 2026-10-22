"""Capture orchestration: the gate, the route, the client, and the refusal policy."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import capture as cap
from casesignal.drafter import session as sess
from casesignal.drafter.shapes.base import (
    RECORD_LIST_AMBIGUOUS,
    RECORD_LIST_BOUNDED,
    CaptureResult,
    HttpClient,
)
from casesignal.etl.services.polite_http import DisallowedHost
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
    Page,
    Status,
)

LISTING = """
<html><body>
  <a class="case" href="/cases/1">Ann Example</a>
  <a class="case" href="/cases/2">Bob Brown</a>
</body></html>
"""
LISTING_PAGED = """
<html><body>
  <a class="case" href="/cases/1">Ann Example</a>
  <a class="next" href="/list?page=2">Next</a>
</body></html>
"""
LISTING_PAGE_2 = """
<html><body>
  <a class="case" href="/cases/2">Bob Brown</a>
</body></html>
"""
# No records, but still linking onwards: the walk stops short of the source.
INTERSTITIAL = """
<html><body><p>Scheduled maintenance</p><a class="next" href="/list?page=3">Next</a></body></html>
"""
NOTHING = "<html><body><p>nothing a selector here recognises</p></body></html>"
BLOCK_PAGE = "<html><head><title>Just a moment...</title></head><body>cf</body></html>"

EMBEDDED = json.dumps({"data": [{"id": "1", "name": "Ann"}, {"id": "2", "name": "Bob"}]})
EMBEDDED_AMBIGUOUS = json.dumps(
    {"data": [{"id": "1", "name": "Ann"}], "results": [{"county": "Tulsa"}]}
)
# One record list, named by the source, beside an array big enough to exhaust the
# search's width budget. The rows are right; the search cannot prove they are unique.
EMBEDDED_BOUNDED = json.dumps(
    {
        "nav": [{"label": f"n{i}"} for i in range(600)],
        "results": [{"id": str(i), "name": f"case {i}"} for i in range(40)],
    }
)
# Both at once: the search ran out of width AND the document named two plausible
# lists. Ambiguity is the stronger statement and has to win, or a document that never
# settled the question is downgraded to "we stopped looking" and waved through.
EMBEDDED_BOUNDED_AND_AMBIGUOUS = json.dumps(
    {
        "nav": [{"label": f"n{i}"} for i in range(600)],
        "data": [{"id": str(i)} for i in range(40)],
        "results": [{"county": "Tulsa"}],
    }
)
# No list under any known record key; the shallowest list of objects is all there is.
EMBEDDED_GUESSED = json.dumps({"stuff": [{"id": "1"}, {"id": "2"}]})
# No record list at all, by name or by guess.
EMBEDDED_UNREADABLE = json.dumps({"title": "Cold cases", "count": 40})


@dataclass(frozen=True)
class FakeResponse:
    text: str
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def content(self) -> bytes:
        return self.text.encode()


class Blocked(Exception):
    """A transport error shaped like httpx.HTTPStatusError: it carries the response."""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        super().__init__(f"{response.status_code} for url")


class FakeClient:
    def __init__(
        self,
        pages: dict[str, str],
        *,
        raises: Exception | None = None,
        raises_on: str | None = None,
        status: int = 200,
    ) -> None:
        self.pages = pages
        self.raises: Exception | None = raises
        self.raises_on = raises_on
        self.status = status
        self.requested: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.requested.append(url)
        if self.raises is not None and self.raises_on in (None, url):
            raise self.raises
        return FakeResponse(text=self.pages[url], status_code=self.status)


class Factory:
    """Records every client this run built, and hands out the next scripted one."""

    def __init__(self, *clients: FakeClient) -> None:
        self.clients = list(clients)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> HttpClient:
        self.calls.append(kwargs)
        return self.clients[min(len(self.calls) - 1, len(self.clients) - 1)]


def _accepted(**over: Any) -> Candidate:
    base: dict[str, Any] = dict(
        id="ok__osbi",
        level=Level.STATE,
        state="OK",
        index_url="https://oklahoma.gov/osbi/cold-cases.html",
        channel=Channel.WEB,
        agency="Oklahoma State Bureau of Investigation",
        status=Status.ACCEPTED,
        gates=Gates(cold_homicide=GateResult.PASS, official_first_party=GateResult.PASS),
    )
    base.update(over)
    return Candidate(**base)


def _run(
    candidate: Candidate,
    tmp_path: Path,
    client: FakeClient | Factory,
    **over: Any,
) -> cap.CaptureOutcome:
    factory = client if isinstance(client, Factory) else Factory(client)
    kwargs: dict[str, Any] = dict(
        draft_dir=tmp_path / "draft",
        fixtures_dir=tmp_path / "draft" / "fx",
        client_factory=factory,
        now="2026-08-31T14:02:11Z",
        nonce="a3f9",
    )
    kwargs.update(over)
    return cap.capture(candidate, **kwargs)


def _listing_client() -> FakeClient:
    return FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": LISTING})


# --- identity ---


def test_adapter_name_is_state_plus_agency_slug() -> None:
    assert cap.adapter_name_for(_accepted()) == "cold_case_ok_osbi"


def test_adapter_name_prefers_a_parenthesised_acronym() -> None:
    candidate = _accepted(agency="Oklahoma State Bureau of Investigation (OSBI)")
    assert cap.adapter_name_for(candidate) == "cold_case_ok_osbi"


def test_adapter_name_builds_an_acronym_from_three_significant_words() -> None:
    candidate = _accepted(state="AR", agency="Arkansas State Police")
    assert cap.adapter_name_for(candidate) == "cold_case_ar_asp"


def test_adapter_name_uses_an_acronym_the_name_already_carries() -> None:
    candidate = _accepted(state="MN", agency="Minnesota BCA")
    assert cap.adapter_name_for(candidate) == "cold_case_mn_bca"


def test_adapter_name_keeps_the_words_of_a_two_word_agency() -> None:
    candidate = _accepted(state="MD", agency="Harford County")
    assert cap.adapter_name_for(candidate) == "cold_case_md_harford_county"


def test_adapter_name_falls_back_to_the_state_when_there_is_no_agency() -> None:
    assert cap.adapter_name_for(_accepted(agency=None)) == "cold_case_ok"


def test_source_key_appends_the_capture_date() -> None:
    assert cap.source_key_for(_accepted(), "2026-08-31") == "cold_case_ok_osbi_2026_08_31"


def test_an_operator_supplied_adapter_name_wins() -> None:
    assert cap.adapter_name_for(_accepted(), override="cold_case_ok_osbi2") == "cold_case_ok_osbi2"
    assert (
        cap.source_key_for(_accepted(), "2026-08-31", override="cold_case_wy_dci")
        == "cold_case_wy_dci_2026_08_31"
    )


@pytest.mark.parametrize(
    "override",
    [
        "Cold_Case_OK",
        "cold case ok",
        "9_cold_case",
        "cold-case-ok",
        "",
        # `$` with `re.match` accepts a trailing newline, and a name carrying one
        # becomes a directory, a YAML key, and `cold_case_ok\n_2026_08_31`.
        "cold_case_ok\n",
        "cold_case_ok\nrm -rf",
    ],
)
def test_an_adapter_name_that_is_not_a_package_name_is_refused(override: str) -> None:
    with pytest.raises(cap.Refused, match="house form"):
        cap.adapter_name_for(_accepted(), override=override)


def test_an_adapter_name_too_long_to_be_a_filename_is_refused() -> None:
    """The name is a path component in every file the scaffold generates."""
    assert len(cap.adapter_name_for(_accepted(), override="c" + "a" * 63)) == 64
    with pytest.raises(cap.Refused, match="over the 64-character limit"):
        cap.adapter_name_for(_accepted(), override="c" + "a" * 64)


def test_a_derived_adapter_name_is_bounded_too() -> None:
    """The constraint belongs to the name, not to whoever supplied it."""
    runaway = _accepted(state="MD", agency=f"{'Aaaaaaaaaa' * 4} {'Bbbbbbbbbb' * 4}")
    with pytest.raises(cap.Refused, match="derived from the candidate"):
        cap.adapter_name_for(runaway)


def test_the_override_is_what_lands_in_the_brief(tmp_path: Path) -> None:
    _run(_accepted(), tmp_path, _listing_client(), adapter_name="cold_case_ok_osbi_v2")
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["adapter_name"] == "cold_case_ok_osbi_v2"
    assert brief["source_key"] == "cold_case_ok_osbi_v2_2026_08_31"


def test_a_bad_override_refuses_before_anything_is_fetched(tmp_path: Path) -> None:
    factory = Factory(_listing_client())
    with pytest.raises(cap.Refused, match="house form"):
        _run(_accepted(), tmp_path, factory, adapter_name="Cold Case OK")
    assert factory.calls == []


# --- the gate ---


def test_refuses_a_candidate_that_is_not_accepted(tmp_path: Path) -> None:
    with pytest.raises(cap.Refused, match="status"):
        _run(_accepted(status=Status.CANDIDATE), tmp_path, _listing_client())


def test_refuses_when_a_hard_gate_did_not_pass(tmp_path: Path) -> None:
    gates = Gates(cold_homicide=GateResult.UNKNOWN, official_first_party=GateResult.PASS)
    with pytest.raises(cap.Refused, match="gate"):
        _run(_accepted(gates=gates), tmp_path, _listing_client())


def test_refuses_a_candidate_with_no_gates_at_all(tmp_path: Path) -> None:
    with pytest.raises(cap.Refused, match="gate"):
        _run(_accepted(gates=None), tmp_path, _listing_client())


@pytest.mark.parametrize(
    "page_type",
    ["pdf", "pdfs", "pdfs_table", "table_of_pdfs", "pdfs listing", "scanned_pdfs_page", "PDF"],
)
def test_the_pdf_gate_matches_the_stem_however_it_is_spelled(
    tmp_path: Path, page_type: str
) -> None:
    """The PDF check is a refusal, so it is matched loosely on purpose.

    Token boundaries exist to stop a routing token from sending a source to the wrong
    shape module, which is silent. This gate fails the other way: too loose costs a
    refusal an operator can argue with, too tight drafts a source with no shape module
    behind it. A page whose records are PDFs is that source however it is spelled.
    """
    with pytest.raises(cap.Refused, match="PDF"):
        _run(_accepted(page_type=page_type), tmp_path, _listing_client())


def test_refuses_js_rendered_and_pdf_sources(tmp_path: Path) -> None:
    for over, msg in (({"needs_js": True}, "JavaScript"), ({"page_type": "pdf"}, "PDF")):
        with pytest.raises(cap.Refused, match=msg):
            _run(_accepted(**over), tmp_path, _listing_client())


def test_refuses_a_non_https_index_url(tmp_path: Path) -> None:
    with pytest.raises(cap.Refused, match="https"):
        _run(_accepted(index_url="http://oklahoma.gov/x"), tmp_path, _listing_client())


def test_the_gate_refuses_before_any_client_is_built(tmp_path: Path) -> None:
    factory = Factory(_listing_client())
    with pytest.raises(cap.Refused):
        _run(_accepted(status=Status.REJECTED), tmp_path, factory)
    assert factory.calls == []


# --- the client ---


def test_allowlists_only_the_candidate_host(tmp_path: Path) -> None:
    factory = Factory(_listing_client())
    _run(_accepted(), tmp_path, factory)
    assert set(factory.calls[0]["allowed_hosts"]) == {"oklahoma.gov"}


def test_passes_no_robots_bypass_at_all(tmp_path: Path) -> None:
    factory = Factory(_listing_client())
    _run(_accepted(), tmp_path, factory)
    assert set(factory.calls[0]["bypass_robots_hosts"]) == set()


def test_a_capture_starts_on_httpx_unless_the_candidate_says_otherwise(tmp_path: Path) -> None:
    factory = Factory(_listing_client())
    outcome = _run(_accepted(), tmp_path, factory)
    assert factory.calls[0]["tls_impersonate"] is False
    assert outcome.transport == "httpx"


def test_a_candidate_flagged_for_tls_impersonation_starts_on_curl_cffi(tmp_path: Path) -> None:
    factory = Factory(_listing_client())
    outcome = _run(_accepted(tls_impersonate_needed=True), tmp_path, factory)
    assert factory.calls[0]["tls_impersonate"] is True
    assert outcome.transport == "curl_cffi"


# --- routing ---


class _Spy:
    def __init__(self, result: CaptureResult | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.result = result or CaptureResult(records_captured=1, records_total=1)

    def __call__(self, *args: Any, **kwargs: Any) -> CaptureResult:
        self.calls.append(args)
        return self.result


def _spies(monkeypatch: pytest.MonkeyPatch) -> tuple[_Spy, _Spy]:
    html, feed = _Spy(), _Spy()
    monkeypatch.setattr(cap, "capture_html", html)
    monkeypatch.setattr(cap, "capture_json", feed)
    return html, feed


def test_a_web_candidate_routes_to_the_html_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html, feed = _spies(monkeypatch)
    outcome = _run(_accepted(page_type="html_listing"), tmp_path, _listing_client())
    assert outcome.shape == "html"
    assert len(html.calls) == 1 and feed.calls == []
    assert outcome.session.shape == "html"


def test_a_web_page_holding_a_json_payload_routes_to_the_json_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html, feed = _spies(monkeypatch)
    outcome = _run(_accepted(page_type="html_embedded_json"), tmp_path, _listing_client())
    assert outcome.shape == "embedded_json"
    assert len(feed.calls) == 1 and html.calls == []


def test_a_socrata_candidate_routes_to_the_json_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html, feed = _spies(monkeypatch)
    candidate = _accepted(channel=Channel.SOCRATA, dataset_id="ab12-cd34", page_type="api_json")
    outcome = _run(candidate, tmp_path, _listing_client())
    assert outcome.shape == "socrata"
    assert len(feed.calls) == 1 and html.calls == []


def test_an_arcgis_candidate_routes_to_the_json_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _spies(monkeypatch)
    candidate = _accepted(channel=Channel.ARCGIS, page_type=None)
    assert _run(candidate, tmp_path, _listing_client()).shape == "arcgis"


def test_refuses_a_feed_channel_whose_page_type_says_html(tmp_path: Path) -> None:
    candidate = _accepted(channel=Channel.SOCRATA, page_type="html_table")
    with pytest.raises(cap.Refused, match="channel says feed"):
        _run(candidate, tmp_path, _listing_client())


def test_refuses_a_page_type_that_names_neither_shape(tmp_path: Path) -> None:
    with pytest.raises(cap.Refused, match="neither an HTML page nor a JSON payload"):
        _run(_accepted(page_type="carousel"), tmp_path, _listing_client())


def test_a_missing_page_type_is_an_ordinary_web_page(tmp_path: Path) -> None:
    assert cap.route(_accepted(page_type=None)) == "html"
    assert cap.route(_accepted(page_type="   ")) == "html"


@pytest.mark.parametrize("page_type", ["capias", "therapist", "rapid", "feedback"])
def test_a_word_that_merely_contains_a_route_token_does_not_route(page_type: str) -> None:
    """Substring matching would send "capias" to the JSON shape on the "api" inside it."""
    with pytest.raises(cap.Refused, match="neither an HTML page nor a JSON payload"):
        cap.route(_accepted(page_type=page_type))


@pytest.mark.parametrize(
    ("page_type", "shape"),
    [
        ("api_json", "embedded_json"),
        ("html_embedded_json", "embedded_json"),
        ("geojson", "embedded_json"),
        ("json-api", "embedded_json"),
        ("html", "html"),
        ("html_table", "html"),
        ("listing page", "html"),
    ],
)
def test_the_tokens_that_should_route_still_route(page_type: str, shape: str) -> None:
    assert cap.route(_accepted(page_type=page_type)) == shape


# --- the shape modules, for real ---


def test_an_html_capture_reports_a_census_and_names_its_fixtures(tmp_path: Path) -> None:
    outcome = _run(_accepted(), tmp_path, _listing_client())
    assert outcome.result.records_captured == 2
    assert outcome.result.records_total == 2
    assert outcome.result.listing_paths == ["listing_1.html"]
    assert (tmp_path / "draft" / "fx" / "listing_1.html").is_file()
    assert outcome.session.fixtures_root == "fx"


def test_the_detail_sample_bound_reaches_the_html_shape(tmp_path: Path) -> None:
    pages = {
        "https://oklahoma.gov/osbi/cold-cases.html": LISTING,
        "https://oklahoma.gov/cases/1": "<html><body><strong>AGE:</strong> 34</body></html>",
        "https://oklahoma.gov/cases/2": "<html><body><strong>AGE:</strong> 51</body></html>",
    }
    candidate = _accepted(
        detail_url_pattern="https://oklahoma.gov/cases/{id}",
        fields={
            "victim_age": FieldSpec(present=True, location=Location.STRUCTURED, page=Page.DETAIL)
        },
    )
    whole = _run(candidate, tmp_path / "whole", FakeClient(pages))
    assert len(whole.result.detail_paths) == 2

    sampled = _run(candidate, tmp_path / "sampled", FakeClient(pages), detail_sample=1)
    assert len(sampled.result.detail_paths) == 1


def test_an_embedded_json_capture_runs_through_the_json_shape(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED})
    outcome = _run(_accepted(page_type="embedded_json"), tmp_path, client)
    assert outcome.shape == "embedded_json"
    assert outcome.result.records_captured == 2
    assert outcome.result.records_total == 2


# --- the shape of `now` ---


@pytest.mark.parametrize(
    "now",
    ["2026-08-31T14:02:11.481Z", "2026-08-31T14:02:11+00:00", "2026-08-31", "not-a-time"],
)
def test_refuses_a_timestamp_that_is_not_filename_safe(tmp_path: Path, now: str) -> None:
    with pytest.raises(cap.Refused, match="YYYY-MM-DDTHH:MM:SSZ"):
        _run(_accepted(), tmp_path, _listing_client(), now=now)


def test_refuses_a_timestamp_carrying_a_trailing_newline(tmp_path: Path) -> None:
    """Caught by the shape check, not by strptime: `$` would have let it through."""
    with pytest.raises(cap.Refused, match="YYYY-MM-DDTHH:MM:SSZ form"):
        _run(_accepted(), tmp_path, _listing_client(), now="2026-08-31T14:02:11Z\n")


@pytest.mark.parametrize("now", ["2026-13-45T99:99:99Z", "2026-02-30T00:00:00Z"])
def test_refuses_a_timestamp_that_is_shaped_right_but_is_not_a_date(
    tmp_path: Path, now: str
) -> None:
    """`source_key` would otherwise read cold_case_ok_osbi_2026_13_45."""
    with pytest.raises(cap.Refused, match="not a real instant"):
        _run(_accepted(), tmp_path, _listing_client(), now=now)


def test_the_session_id_carries_only_safe_characters(tmp_path: Path) -> None:
    outcome = _run(_accepted(), tmp_path, _listing_client())
    assert outcome.session.session_id == "20260831T140211Z-a3f9"


# --- the fixtures directory ---


def test_refuses_a_fixtures_directory_outside_the_draft_directory(tmp_path: Path) -> None:
    with pytest.raises(cap.Refused, match="outside the draft directory"):
        _run(_accepted(), tmp_path, _listing_client(), fixtures_dir=tmp_path / "elsewhere")


def test_refuses_a_fixtures_directory_that_traverses_out(tmp_path: Path) -> None:
    with pytest.raises(cap.Refused, match="outside the draft directory"):
        _run(
            _accepted(),
            tmp_path,
            _listing_client(),
            fixtures_dir=tmp_path / "draft" / ".." / "escaped",
        )


def test_refuses_a_fixtures_directory_symlinked_out_of_the_draft_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "draft").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "draft" / "fx").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(cap.Refused, match="outside the draft directory"):
        _run(_accepted(), tmp_path, _listing_client())


def test_fixtures_beside_the_manifest_are_allowed(tmp_path: Path) -> None:
    outcome = _run(_accepted(), tmp_path, _listing_client(), fixtures_dir=tmp_path / "draft")
    assert outcome.session.fixtures_root == ""
    assert (tmp_path / "draft" / "listing_1.html").is_file()


# --- sessions ---


def test_a_second_capture_continues_the_session_it_finds(tmp_path: Path) -> None:
    first = _run(_accepted(), tmp_path, _listing_client())
    resumed_client = _listing_client()
    second = _run(_accepted(), tmp_path, resumed_client)
    assert second.session.session_id == first.session.session_id
    assert resumed_client.requested == []


def test_refresh_starts_a_new_session(tmp_path: Path) -> None:
    first = _run(_accepted(), tmp_path, _listing_client())
    client = _listing_client()
    second = _run(_accepted(), tmp_path, client, now="2026-09-01T09:00:00Z", refresh=True)
    assert second.session.session_id != first.session.session_id
    assert client.requested == ["https://oklahoma.gov/osbi/cold-cases.html"]


def test_a_named_session_id_is_checked_against_the_one_on_disk(tmp_path: Path) -> None:
    outcome = _run(_accepted(), tmp_path, _listing_client())
    with pytest.raises(sess.SessionMismatch, match="cannot resume as"):
        _run(_accepted(), tmp_path, _listing_client(), session_id="20260101T000000Z-zzzz")
    resumed = _run(_accepted(), tmp_path, _listing_client(), session_id=outcome.session.session_id)
    assert resumed.session.session_id == outcome.session.session_id


def test_refuses_to_continue_a_session_captured_as_another_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(_accepted(), tmp_path, _listing_client())
    _spies(monkeypatch)
    candidate = _accepted(channel=Channel.SOCRATA, dataset_id="ab12-cd34")
    with pytest.raises(cap.Refused, match="one session holds one shape"):
        _run(candidate, tmp_path, _listing_client())


def test_refuses_to_continue_a_session_that_recorded_another_fixtures_root(
    tmp_path: Path,
) -> None:
    _run(_accepted(), tmp_path, _listing_client())
    with pytest.raises(cap.Refused, match="records fixtures_root"):
        _run(
            _accepted(),
            tmp_path,
            _listing_client(),
            fixtures_dir=tmp_path / "draft" / "other",
        )


# --- the corpus ---


def test_a_partial_prune_is_reported_rather_than_swallowed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    paged = {
        "https://oklahoma.gov/osbi/cold-cases.html": LISTING_PAGED,
        "https://oklahoma.gov/list?page=2": LISTING_PAGE_2,
    }
    _run(_accepted(), tmp_path, FakeClient(paged))
    # The source drops its second page; the first fixture is gone from disk, so the
    # resumed run re-fetches it and never reaches page 2.
    (tmp_path / "draft" / "fx" / "listing_1.html").unlink()
    shrunk = dict(paged)
    shrunk["https://oklahoma.gov/osbi/cold-cases.html"] = LISTING

    with caplog.at_level(logging.WARNING, logger="casesignal.drafter.capture"):
        outcome = _run(_accepted(), tmp_path, FakeClient(shrunk))

    assert outcome.dropped_urls == ("https://oklahoma.gov/list?page=2",)
    assert "dropped 1 fixture" in caplog.text
    assert [f.url for f in outcome.session.fixtures] == [
        "https://oklahoma.gov/osbi/cold-cases.html"
    ]


def test_refuses_when_a_capture_replaces_the_whole_previous_corpus(tmp_path: Path) -> None:
    _run(_accepted(), tmp_path, _listing_client())
    moved = _accepted(index_url="https://oklahoma.gov/osbi/unsolved.html")
    client = FakeClient({"https://oklahoma.gov/osbi/unsolved.html": LISTING})
    with pytest.raises(cap.IncompleteCapture, match="whole previous corpus") as raised:
        _run(moved, tmp_path, client)
    assert raised.value.outcome.result.records_captured == 2


# --- the refusal policy ---


def test_refuses_a_capture_that_produced_no_records(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": NOTHING})
    with pytest.raises(cap.IncompleteCapture, match="no records") as raised:
        _run(_accepted(), tmp_path, client)
    assert raised.value.outcome.result.records_captured == 0
    assert not (tmp_path / "draft" / "brief.json").exists()


def test_refuses_a_walk_that_stopped_while_more_was_on_offer(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "https://oklahoma.gov/osbi/cold-cases.html": LISTING_PAGED,
            "https://oklahoma.gov/list?page=2": INTERSTITIAL,
        }
    )
    with pytest.raises(cap.IncompleteCapture, match="still offering more") as raised:
        _run(_accepted(), tmp_path, client)
    assert raised.value.outcome.result.truncated is True
    assert raised.value.outcome.result.records_captured == 1


def test_refuses_a_payload_that_named_two_plausible_record_lists(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED_AMBIGUOUS})
    with pytest.raises(
        cap.IncompleteCapture, match="named more than one plausible record list"
    ) as raised:
        _run(_accepted(page_type="embedded_json"), tmp_path, client)
    assert raised.value.outcome.result.records_captured == 1
    assert raised.value.outcome.result.record_list_identified is False
    assert raised.value.outcome.result.record_list_basis == RECORD_LIST_AMBIGUOUS


def test_ambiguity_outranks_a_spent_search_budget(tmp_path: Path) -> None:
    """A document that named two lists did not settle the question however much was read.

    Both conditions hold here, and only one of them may be downgraded to a warning.
    Reporting the spent budget instead would wave through a payload whose record list
    is genuinely undecided -- the exact case the refusal exists for.
    """
    client = FakeClient(
        {"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED_BOUNDED_AND_AMBIGUOUS}
    )
    with pytest.raises(
        cap.IncompleteCapture, match="named more than one plausible record list"
    ) as raised:
        _run(_accepted(page_type="embedded_json"), tmp_path, client)
    assert raised.value.outcome.result.record_list_basis == RECORD_LIST_AMBIGUOUS


def test_refuses_a_payload_whose_record_list_was_only_guessed(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED_GUESSED})
    with pytest.raises(cap.IncompleteCapture, match="no list under any known record key"):
        _run(_accepted(page_type="embedded_json"), tmp_path, client)


def test_refuses_a_payload_holding_no_record_list_at_all(tmp_path: Path) -> None:
    """Not the same finding as an empty corpus, and it must not borrow that message.

    A document that named an empty list served a source with no cases; this one never
    said where to look. Both hold zero records, and only the second needs a person.
    """
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED_UNREADABLE})
    with pytest.raises(cap.IncompleteCapture, match="no record list was found") as raised:
        _run(_accepted(page_type="embedded_json"), tmp_path, client)
    assert raised.value.outcome.result.records_captured == 0


def test_a_bounded_payload_search_keeps_its_records_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The reviewer's case C: the right 40 records, declined for the nav menu's sake.

    The search hit its width bound on 600 unrelated objects, so it cannot claim the
    list it found is the only one named — but the list it found IS the one the source
    named. Refusing here would throw away a correct corpus and prescribe a remedy no
    candidate field can express.
    """
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED_BOUNDED})
    with caplog.at_level(logging.WARNING, logger="casesignal.drafter.capture"):
        outcome = _run(_accepted(page_type="embedded_json"), tmp_path, client)

    assert outcome.result.records_captured == 40
    assert outcome.result.record_list_identified is False
    assert outcome.result.record_list_basis == RECORD_LIST_BOUNDED
    # The census is still withheld -- that part was always right.
    assert outcome.result.records_total is None
    assert "width and depth bounds" in caplog.text
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["record_list_basis"] == "bounded"
    assert brief["record_list_identified"] is False


def test_refuses_a_capture_holding_a_fixture_the_server_refused(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": LISTING}, status=403)
    with pytest.raises(cap.IncompleteCapture, match="error status"):
        _run(_accepted(), tmp_path, client)


# --- accepted findings ---


def _truncating_client() -> FakeClient:
    """A listing whose next link points back at the page already captured.

    html.py:129 calls that truncated because it cannot tell a disabled pager from
    half a listing -- and on a real one-page listing it is the former, which is why
    this refusal needs an operator escape rather than only a refusal.
    """
    cyclic = """
    <html><body>
      <a class="case" href="/cases/1">Ann Example</a>
      <a class="case" href="/cases/2">Bob Brown</a>
      <a class="next" href="/osbi/cold-cases.html">Next</a>
    </body></html>
    """
    return FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": cyclic})


def test_a_cyclic_pager_on_a_complete_one_page_listing_refuses_by_default(
    tmp_path: Path,
) -> None:
    with pytest.raises(cap.IncompleteCapture, match="still offering more"):
        _run(_accepted(), tmp_path, _truncating_client())


def test_an_accepted_truncation_lets_the_capture_through(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="casesignal.drafter.capture"):
        outcome = _run(
            _accepted(), tmp_path, _truncating_client(), accept_partial={cap.ACCEPT_TRUNCATED}
        )
    assert outcome.result.truncated is True
    assert outcome.result.records_captured == 2
    assert "accepted 'truncated'" in caplog.text
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["accepted_findings"] == ["truncated"]
    assert brief["truncated"] is True


def test_an_accepted_empty_corpus_lets_the_capture_through(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": NOTHING})
    outcome = _run(_accepted(), tmp_path, client, accept_partial=[cap.ACCEPT_EMPTY])
    assert outcome.result.records_captured == 0
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["accepted_findings"] == ["empty"]


def test_an_accepted_unidentified_list_lets_the_capture_through(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED_AMBIGUOUS})
    outcome = _run(
        _accepted(page_type="embedded_json"),
        tmp_path,
        client,
        accept_partial={cap.ACCEPT_UNIDENTIFIED},
    )
    assert outcome.result.record_list_identified is False
    assert outcome.result.records_captured == 1


def test_one_acceptance_does_not_forgive_another_finding(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": NOTHING})
    with pytest.raises(cap.IncompleteCapture, match="produced no records"):
        _run(_accepted(), tmp_path, client, accept_partial={cap.ACCEPT_TRUNCATED})


def test_refuses_a_listing_whose_whole_list_is_one_generic_container(tmp_path: Path) -> None:
    """The HTML half of the wrapper finding, through the real refusal policy.

    Twelve `div.case-row` rows inside one `<article>` used to come back
    `captured=1 total=1`, and the inventory endorsed it: `select_one` over the wrapper
    payload scores every locator 1/1, so the floors were non-vacuous and the run
    resolved PASS over a parser returning one blob.
    """
    rows = "".join(f'<div class="case-row"><a href="/c/{i}">Case {i}</a></div>' for i in range(12))
    wrapped = f"<html><body><article><h1>Cold cases</h1>{rows}</article></body></html>"
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": wrapped})

    with pytest.raises(cap.IncompleteCapture, match="wrappers around the records") as raised:
        _run(_accepted(), tmp_path, client)

    assert raised.value.outcome.result.records_captured == 1
    assert raised.value.outcome.result.records_total is None
    assert raised.value.outcome.result.record_list_basis == "wrapped"


def test_an_accepted_wrapper_finding_still_does_not_get_its_census_back(
    tmp_path: Path,
) -> None:
    """An acceptance forgives the refusal; it does not make one blob a count of one."""
    rows = "".join(f'<div class="case-row"><a href="/c/{i}">Case {i}</a></div>' for i in range(12))
    wrapped = f"<html><body><article>{rows}</article></body></html>"
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": wrapped})

    outcome = _run(_accepted(), tmp_path, client, accept_partial={cap.ACCEPT_UNIDENTIFIED})

    assert outcome.result.records_captured == 1
    assert outcome.result.records_total is None
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["records_total"] is None


# --- the source's own stated count ---


def test_a_corpus_far_short_of_the_stated_count_is_refused(tmp_path: Path) -> None:
    """The spec's own cross-check, and the one corroboration from outside the walk.

    `design.md:352-355` asks for the record count "checked against the source's stated
    total where one exists". ``case_count`` used to be written into brief.json and read
    by nothing, so a two-record census of a 307-case source resolved PASS.
    """
    candidate = _accepted(
        case_count=CaseCount(value=307, confidence=Confidence.VISIBLE, basis="header text")
    )
    with pytest.raises(cap.IncompleteCapture, match="Source Scout recorded this source") as raised:
        _run(candidate, tmp_path, _listing_client())
    assert raised.value.outcome.result.records_captured == 2


def test_an_accepted_count_mismatch_lets_the_capture_through(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    candidate = _accepted(case_count=CaseCount(value=307, confidence=Confidence.VISIBLE))
    with caplog.at_level(logging.WARNING, logger="casesignal.drafter.capture"):
        outcome = _run(
            candidate,
            tmp_path,
            _listing_client(),
            accept_partial={cap.ACCEPT_COUNT_MISMATCH},
        )
    assert outcome.result.records_captured == 2
    assert "accepted 'count_mismatch'" in caplog.text
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["accepted_findings"] == ["count_mismatch"]


@pytest.mark.parametrize(
    ("stated", "confidence"),
    [
        (2, Confidence.EXACT),
        (2, None),
        (2, Confidence.PROBED),
        (3, Confidence.VISIBLE),  # 2 of 3 is inside the 50% visible tolerance
        (4, Confidence.VISIBLE),  # 2 of 4 is exactly on it
    ],
)
def test_a_corpus_inside_the_tolerance_for_its_confidence_stands(
    tmp_path: Path, stated: int, confidence: Confidence | None
) -> None:
    candidate = _accepted(case_count=CaseCount(value=stated, confidence=confidence))
    outcome = _run(candidate, tmp_path, _listing_client())
    assert outcome.result.records_captured == 2


def test_an_exact_count_one_above_the_corpus_is_refused(tmp_path: Path) -> None:
    """EXACT means a catalog or an endpoint answered with the number; there is no slack."""
    candidate = _accepted(case_count=CaseCount(value=3, confidence=Confidence.EXACT))
    with pytest.raises(cap.IncompleteCapture, match="Source Scout recorded this source"):
        _run(candidate, tmp_path, _listing_client())


def test_a_probed_count_is_held_tighter_than_a_visible_one(tmp_path: Path) -> None:
    """The same corpus and the same number, refused or not by how the number was got."""
    probed = _accepted(case_count=CaseCount(value=3, confidence=Confidence.PROBED))
    with pytest.raises(cap.IncompleteCapture, match="Source Scout recorded this source"):
        _run(probed, tmp_path, _listing_client())


def test_over_capturing_the_stated_count_is_warned_about_and_stands(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A listing that also carries solved cases is ordinary; every false census under-counts."""
    candidate = _accepted(case_count=CaseCount(value=1, confidence=Confidence.EXACT))
    with caplog.at_level(logging.WARNING, logger="casesignal.drafter.capture"):
        outcome = _run(candidate, tmp_path, _listing_client())
    assert outcome.result.records_captured == 2
    assert "against a stated count of 1" in caplog.text


def test_a_candidate_with_no_stated_count_is_not_cross_checked(tmp_path: Path) -> None:
    outcome = _run(_accepted(case_count=CaseCount(value=None)), tmp_path, _listing_client())
    assert outcome.result.records_captured == 2


def test_the_cross_check_reads_the_corpus_size_not_the_sample() -> None:
    """A deliberately scoped capture reports a total ABOVE what it captured.

    An ArcGIS layer answering ``returnCountOnly`` and an embedded payload larger than
    the cap both do this, and that total is what the stated count is a statement about.
    Comparing the sample instead would refuse every scoped capture on the spot.
    """
    result = CaptureResult(records_captured=50, records_total=307)
    session = sess.CaptureSession(
        session_id="20260831T140211Z-a3f9", shape="html", started_at="2026-08-31T14:02:11Z"
    )
    outcome = cap.CaptureOutcome(result=result, session=session, shape="html")
    candidate = _accepted(case_count=CaseCount(value=307, confidence=Confidence.EXACT))

    cap._check_against_the_stated_count(outcome, candidate, frozenset())


@pytest.mark.parametrize(
    ("finding", "run_it"),
    [
        (
            cap.ACCEPT_EMPTY,
            lambda tmp: (
                _accepted(),
                FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": NOTHING}),
            ),
        ),
        (
            cap.ACCEPT_TRUNCATED,
            lambda tmp: (_accepted(), _truncating_client()),
        ),
        (
            cap.ACCEPT_UNIDENTIFIED,
            lambda tmp: (
                _accepted(page_type="embedded_json"),
                FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": EMBEDDED_AMBIGUOUS}),
            ),
        ),
        (
            cap.ACCEPT_COUNT_MISMATCH,
            lambda tmp: (
                _accepted(case_count=CaseCount(value=307, confidence=Confidence.VISIBLE)),
                _listing_client(),
            ),
        ),
    ],
)
def test_every_refusal_names_the_flag_and_the_token_that_clears_it(
    tmp_path: Path, finding: str, run_it: Any
) -> None:
    """A remedy an operator cannot act on from the message that requires it.

    All four ended "accept the finding by name" and none of them wrote the name. The
    flag and its tokens lived in the module docstring, in `--help` and in the run-book,
    never in the sentence being read. Same defect shape as prescribing a `--force` that
    does not exist, one step milder.
    """
    candidate, client = run_it(tmp_path)

    with pytest.raises(cap.IncompleteCapture) as caught:
        _run(candidate, tmp_path, client)

    message = str(caught.value)
    assert f"--accept-partial {finding}" in message
    # And the token really is the one that clears it, not just a string in the text.
    _run(candidate, tmp_path, client, accept_partial={finding})


def test_no_acceptance_forgives_a_fixture_the_server_refused(tmp_path: Path) -> None:
    client = FakeClient({"https://oklahoma.gov/osbi/cold-cases.html": LISTING}, status=403)
    with pytest.raises(cap.IncompleteCapture, match="error status"):
        _run(_accepted(), tmp_path, client, accept_partial=cap.ACCEPTABLE)


def test_an_acceptance_that_names_no_finding_is_refused(tmp_path: Path) -> None:
    factory = Factory(_listing_client())
    with pytest.raises(cap.Refused, match="not a finding this capture can produce"):
        _run(_accepted(), tmp_path, factory, accept_partial={"everything"})
    assert factory.calls == []


def test_nothing_is_accepted_by_default(tmp_path: Path) -> None:
    _run(_accepted(), tmp_path, _listing_client())
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["accepted_findings"] == []


# --- the second-host refusal (the client's message is inert on this path) ---


def test_a_second_host_is_refused_with_a_remedy_that_is_not_a_dead_end(
    tmp_path: Path,
) -> None:
    """DisallowedHost is the EXPECTED outcome for a listing that links another host.

    Its own message offers ``_DEFAULT_ALLOWED_HOSTS`` and ``CASESIGNAL_HTTP_EXTRA_HOSTS``,
    and neither is consulted when ``allowed_hosts`` is passed explicitly -- which this
    module always does. An operator following either remedy changes nothing.
    """
    blocked = DisallowedHost(
        "polite_http refuses non-allowlisted host: media.ark.org (url='https://media.ark.org/x'). "
        "Add to _DEFAULT_ALLOWED_HOSTS in polite_http.py or set "
        "CASESIGNAL_HTTP_EXTRA_HOSTS for one-off testing."
    )
    client = FakeClient({}, raises=blocked)
    with pytest.raises(cap.Refused, match="media.ark.org") as raised:
        _run(_accepted(), tmp_path, client)
    message = str(raised.value)
    assert "allowlists exactly the candidate's index host" in message
    assert "are not consulted here" in message


def test_a_disallowed_host_is_not_mistaken_for_a_tls_block(tmp_path: Path) -> None:
    factory = Factory(FakeClient({}, raises=DisallowedHost("nope")), _listing_client())
    with pytest.raises(cap.Refused):
        _run(_accepted(), tmp_path, factory)
    assert len(factory.calls) == 1


# --- the TLS fingerprint retry ---


def _block(**over: Any) -> Blocked:
    kwargs: dict[str, Any] = dict(text=BLOCK_PAGE, status_code=403)
    kwargs.update(over)
    return Blocked(FakeResponse(**kwargs))


def test_a_fingerprint_403_retries_the_whole_capture_over_curl_cffi(tmp_path: Path) -> None:
    factory = Factory(FakeClient({}, raises=_block()), _listing_client())
    outcome = _run(_accepted(), tmp_path, factory)
    assert [call["tls_impersonate"] for call in factory.calls] == [False, True]
    assert outcome.transport == "curl_cffi"
    assert outcome.result.records_captured == 2


def test_a_fingerprint_403_is_recognised_by_a_challenge_header_alone(tmp_path: Path) -> None:
    blocked = _block(text="", headers={"CF-RAY": "8a1b"})
    factory = Factory(FakeClient({}, raises=blocked), _listing_client())
    assert _run(_accepted(), tmp_path, factory).transport == "curl_cffi"


def test_a_fingerprint_403_is_recognised_by_the_server_header_alone(tmp_path: Path) -> None:
    blocked = _block(text="", headers={"Server": "cloudflare"})
    factory = Factory(FakeClient({}, raises=blocked), _listing_client())
    assert _run(_accepted(), tmp_path, factory).transport == "curl_cffi"


def test_a_403_with_no_challenge_evidence_at_all_is_not_retried(tmp_path: Path) -> None:
    factory = Factory(FakeClient({}, raises=_block(text="", headers={})), _listing_client())
    with pytest.raises(Blocked):
        _run(_accepted(), tmp_path, factory)
    assert len(factory.calls) == 1


def test_a_plain_403_is_not_retried(tmp_path: Path) -> None:
    factory = Factory(FakeClient({}, raises=_block(text="Forbidden")), _listing_client())
    with pytest.raises(Blocked):
        _run(_accepted(), tmp_path, factory)
    assert len(factory.calls) == 1


def test_a_404_is_not_retried(tmp_path: Path) -> None:
    factory = Factory(
        FakeClient({}, raises=_block(text=BLOCK_PAGE, status_code=404)), _listing_client()
    )
    with pytest.raises(Blocked):
        _run(_accepted(), tmp_path, factory)
    assert len(factory.calls) == 1


def test_a_capture_already_impersonating_does_not_retry(tmp_path: Path) -> None:
    factory = Factory(FakeClient({}, raises=_block()), _listing_client())
    with pytest.raises(Blocked):
        _run(_accepted(tls_impersonate_needed=True), tmp_path, factory)
    assert len(factory.calls) == 1


def test_the_retry_refetches_the_pages_the_blocked_transport_had_already_taken(
    tmp_path: Path,
) -> None:
    """A retry is a whole capture, not the tail of the one that was blocked.

    Resuming would keep whatever the blocked transport managed to take -- and a
    Cloudflare challenge is routinely served as a 200 before it starts 403ing, so
    those pages are the least trustworthy bytes in the corpus. The fixtures are
    also the evidence for a capture the brief will describe as ``curl_cffi``.
    """
    pages = {
        "https://oklahoma.gov/osbi/cold-cases.html": LISTING_PAGED,
        "https://oklahoma.gov/list?page=2": LISTING_PAGE_2,
    }
    blocked_client = FakeClient(
        pages, raises=_block(), raises_on="https://oklahoma.gov/list?page=2"
    )
    retry_client = FakeClient(pages)
    outcome = _run(_accepted(), tmp_path, Factory(blocked_client, retry_client))

    assert blocked_client.requested == list(pages)
    assert retry_client.requested == list(pages)
    assert outcome.transport == "curl_cffi"
    assert outcome.result.records_captured == 2


def test_the_retry_starts_a_clean_session_rather_than_resuming_the_blocked_one(
    tmp_path: Path,
) -> None:
    """The retry is a fresh session, so the httpx corpus is not blended into it.

    A resumed retry would carry the previous run's fixtures, and the prune at the
    end of the walk would then read as a corpus replacement and refuse the capture
    that just succeeded.
    """
    _run(_accepted(), tmp_path, _listing_client())
    moved = _accepted(index_url="https://oklahoma.gov/osbi/unsolved.html")
    factory = Factory(
        FakeClient({}, raises=_block()),
        FakeClient({"https://oklahoma.gov/osbi/unsolved.html": LISTING}),
    )
    outcome = _run(moved, tmp_path, factory)
    assert outcome.transport == "curl_cffi"
    assert outcome.dropped_urls == ()
    assert [f.url for f in outcome.session.fixtures] == ["https://oklahoma.gov/osbi/unsolved.html"]


# --- the brief ---


def test_the_brief_records_the_listing_record_count(tmp_path: Path) -> None:
    outcome = _run(_accepted(), tmp_path, _listing_client())
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["listing_record_count"] == outcome.result.records_captured == 2
    assert brief["records_total"] == 2
    assert brief["adapter_name"] == "cold_case_ok_osbi"
    assert brief["source_key"] == "cold_case_ok_osbi_2026_08_31"
    assert brief["shape"] == "html"
    assert brief["transport"] == "httpx"
    assert brief["session_id"] == outcome.session.session_id
    assert brief["fixtures_root"] == "fx"
    assert brief["gates"]["cold_homicide"] == "pass"


def test_the_brief_states_no_floors_until_something_has_measured_them(tmp_path: Path) -> None:
    _run(_accepted(), tmp_path, _listing_client())
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert "floors" not in brief


def test_the_brief_announces_that_nothing_has_measured_the_inventory(tmp_path: Path) -> None:
    """An absent `floors` key is not a signal a consumer has to read.

    `brief.get("floors", {})` renders a test module asserting nothing at all, and
    nothing about the file tells the consumer that is what happened.
    """
    _run(_accepted(), tmp_path, _listing_client())
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert brief["inventory_measured"] is False
    assert all(spec["coverage"] is None for spec in brief["fields"].values())


def test_the_brief_is_rewritten_in_place_on_a_second_capture(tmp_path: Path) -> None:
    _run(_accepted(), tmp_path, _listing_client())
    (tmp_path / "draft" / "brief.json").write_text('{"stale": true}')
    _run(_accepted(), tmp_path, _listing_client())
    brief = json.loads((tmp_path / "draft" / "brief.json").read_text())
    assert "stale" not in brief
    assert not list((tmp_path / "draft").glob("brief.json.tmp"))


# --- CaptureInfo ---


def _outcome(**over: Any) -> cap.CaptureOutcome:
    result = CaptureResult(
        listing_paths=["listing_1.html"],
        records_captured=3,
        records_total=None,
        pagination_kind="query_param",
        pagination_detail="a.next",
        **over,
    )
    session = sess.CaptureSession(
        session_id="20260831T140211Z-a3f9", shape="html", started_at="2026-08-31T14:02:11Z"
    )
    return cap.CaptureOutcome(result=result, session=session, shape="html")


def test_capture_info_carries_the_truncation_signal(tmp_path: Path) -> None:
    info = cap.capture_info(_outcome(truncated=True))
    assert info.truncated is True
    assert info.records_total is None


def test_capture_info_carries_the_identification_signal(tmp_path: Path) -> None:
    assert cap.capture_info(_outcome(record_list_identified=False)).record_list_identified is False
    assert cap.capture_info(_outcome()).record_list_identified is True


def test_capture_info_counts_the_listing_records_and_pages(tmp_path: Path) -> None:
    info = cap.capture_info(_outcome())
    assert info.listing_record_count == 3
    assert info.listing_pages == 1
    assert info.fetched_at == "2026-08-31T14:02:11Z"
    assert info.transport == "httpx"
