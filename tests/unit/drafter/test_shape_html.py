from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import session as sess
from casesignal.drafter.shapes.base import ShapeCapture
from casesignal.drafter.shapes.html import (
    FixtureRootMismatch,
    UnsafeFixturePath,
    capture_html,
)
from casesignal.scout.models import Candidate, Channel, FieldSpec, Level, Location, Page

LISTING_1 = """
<html><body>
  <a class="case" href="/cases/1">Ann Example</a>
  <a class="case" href="/cases/2">Bob Brown</a>
  <a class="next" href="/list?page=2">Next</a>
</body></html>
"""
LISTING_2 = """
<html><body>
  <a class="case" href="/cases/3">Cal Cook</a>
</body></html>
"""
DETAIL = "<html><body><strong>AGE:</strong> 34</body></html>"


def _detail(age: int) -> str:
    """A detail page that says which case it is, so a mis-pairing is visible."""
    return f"<html><body><strong>AGE:</strong> {age}</body></html>"


@dataclass(frozen=True)
class FakeResponse:
    text: str
    status_code: int
    content: bytes


class FakeClient:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.requested.append(url)
        body = self.pages[url]
        return FakeResponse(text=body, status_code=200, content=body.encode())


def _candidate(**over: Any) -> Candidate:
    base: dict[str, Any] = dict(
        id="xx__agency",
        level=Level.STATE,
        state="XX",
        index_url="https://ex.gov/list",
        channel=Channel.WEB,
        detail_url_pattern="https://ex.gov/cases/{id}",
        fields={
            "victim_age": FieldSpec(present=True, location=Location.STRUCTURED, page=Page.DETAIL)
        },
    )
    base.update(over)
    return Candidate(**base)


def test_captures_every_listing_page(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "https://ex.gov/list": LISTING_1,
            "https://ex.gov/list?page=2": LISTING_2,
            "https://ex.gov/cases/1": DETAIL,
            "https://ex.gov/cases/2": DETAIL,
            "https://ex.gov/cases/3": DETAIL,
        }
    )
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert len(result.listing_paths) == 2
    assert result.records_captured == 3
    assert result.records_total == 3
    assert result.truncated is False


def test_detail_sample_is_capped(tmp_path: Path) -> None:
    pages = {"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2}
    pages.update({f"https://ex.gov/cases/{i}": DETAIL for i in (1, 2, 3)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=2)

    assert len(result.detail_paths) == 2


def test_list_only_source_fetches_no_detail_pages(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    candidate = _candidate(
        detail_url_pattern=None,
        fields={
            "victim_name": FieldSpec(present=True, location=Location.NARRATIVE, page=Page.LIST)
        },
    )

    result = capture_html(candidate, client, s, tmp_path, tmp_path / "fx")

    assert result.detail_paths == []
    assert result.records_captured == 3
    assert all(r.page == "list" for r in result.records)


def test_resume_skips_already_fetched_urls(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    candidate = _candidate(detail_url_pattern=None)

    capture_html(candidate, client, s, tmp_path, tmp_path / "fx")
    first_count = len(client.requested)
    capture_html(candidate, client, s, tmp_path, tmp_path / "fx")

    assert len(client.requested) == first_count


# --- resume reads the file the URL landed in, not the name this run invented ---


def test_resume_reads_the_path_the_url_was_originally_recorded_to(tmp_path: Path) -> None:
    # Run 1 samples all three details (detail_1/2/3 = cases 1/2/3). Run 2 widens
    # nothing but narrows the sample to two, so the sampler picks cases 1 and 3 —
    # and case 3 is now the SECOND detail slot. A resume keyed on the name this run
    # assigned would read detail_2.html, which holds case 2's page, and pair it with
    # case 3's record: a silently mis-measured inventory. It must read the path the
    # manifest recorded for that URL instead.
    pages = {"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2}
    pages.update({f"https://ex.gov/cases/{i}": _detail(30 + i) for i in (1, 2, 3)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=3)
    after_first = len(client.requested)
    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=2)

    assert len(client.requested) == after_first  # nothing re-fetched
    case_three = next(r for r in result.records if r.key == "listing_2.html#0")
    assert case_three.page == "detail"
    assert "33" in case_three.payload


def test_a_resumed_capture_names_fixtures_that_exist(tmp_path: Path) -> None:
    # The sample narrowed, so case 3 keeps the detail_3.html it landed in last run.
    # Reporting the detail_2.html this run would have given it names a file that is
    # not there and, worse, one that holds another case.
    pages = {"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2}
    pages.update({f"https://ex.gov/cases/{i}": _detail(30 + i) for i in (1, 2, 3)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=3)
    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=2)

    assert result.detail_paths == ["detail_1.html", "detail_3.html"]
    for name in result.listing_paths + result.detail_paths:
        assert (tmp_path / "fx" / name).is_file()


def test_a_widened_sample_still_reports_where_each_page_actually_landed(tmp_path: Path) -> None:
    # Widening the sample interleaves new pages with old ones, so the free ordinal
    # this run reaches for a resumed URL is not the one that URL landed in: case 3
    # sits in detail_2.html from the narrow run while this run's counter is at 5.
    rows = "".join(f'<a class="case" href="/cases/{i}">Case {i}</a>' for i in range(1, 6))
    pages = {"https://ex.gov/list": f"<html><body>{rows}</body></html>"}
    pages.update({f"https://ex.gov/cases/{i}": _detail(30 + i) for i in range(1, 6)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=3)
    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=5)

    assert len(result.detail_paths) == 5
    for name in result.listing_paths + result.detail_paths:
        assert (tmp_path / "fx" / name).is_file()
    third = next(r for r in result.records if r.key == "listing_1.html#2")
    assert "33" in third.payload


def test_a_fixture_name_another_url_holds_is_not_reused(tmp_path: Path) -> None:
    # A resume of a site that lost a listing page hands this run an ordinal the
    # manifest already spent on a different URL. Writing there would leave that
    # record pointing at bytes it does not hash to.
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "listing_2.html").write_bytes(b"stale")
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    sess.record(
        s,
        tmp_path,
        path="listing_2.html",
        url="https://ex.gov/list?page=99",
        status=200,
        body=b"stale",
    )
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.listing_paths == ["listing_1.html", "listing_3.html"]
    assert (tmp_path / "fx" / "listing_2.html").read_bytes() == b"stale"
    # and the manifest no longer names the page this walk never reached
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [f["path"] for f in manifest["fixtures"]] == ["listing_1.html", "listing_3.html"]


def test_refetches_when_the_recorded_fixture_is_gone(tmp_path: Path) -> None:
    # The manifest names a file that is no longer on disk, so the session does not
    # actually hold that page. Re-fetching is the honest response; reading nothing
    # and calling it captured would measure coverage against a hole.
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    candidate = _candidate(detail_url_pattern=None)

    capture_html(candidate, client, s, tmp_path, tmp_path / "fx")
    (tmp_path / "fx" / "listing_1.html").unlink()
    result = capture_html(candidate, client, s, tmp_path, tmp_path / "fx")

    assert client.requested.count("https://ex.gov/list") == 2
    assert result.records_captured == 3
    # and it lands back in its own file: a URL keeps the fixture name it had.
    assert result.listing_paths == ["listing_1.html", "listing_2.html"]


# --- the sample spans the listing rather than its head ---


def test_detail_sample_spans_the_listing(tmp_path: Path) -> None:
    rows = "".join(f'<a class="case" href="/cases/{i}">Case {i}</a>' for i in range(1, 7))
    pages = {"https://ex.gov/list": f"<html><body>{rows}</body></html>"}
    pages.update({f"https://ex.gov/cases/{i}": DETAIL for i in range(1, 7)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=2)

    fetched = [u for u in client.requested if "/cases/" in u]
    assert fetched == ["https://ex.gov/cases/1", "https://ex.gov/cases/6"]


# --- detail URL derivation ---


def test_detail_urls_resolve_from_the_records_own_href(tmp_path: Path) -> None:
    # The pattern points somewhere the listing does not, so only href resolution
    # can produce a URL the fake serves.
    pages = {"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2}
    pages.update({f"https://ex.gov/cases/{i}": DETAIL for i in (1, 2, 3)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(
        _candidate(detail_url_pattern="https://ex.gov/nowhere/{id}"),
        client,
        s,
        tmp_path,
        tmp_path / "fx",
    )

    assert "https://ex.gov/cases/1" in client.requested
    assert not any("nowhere" in u for u in client.requested)


def test_detail_url_pattern_fills_in_when_a_record_has_no_href(tmp_path: Path) -> None:
    listing = '<html><body><article data-case-id="A7">Ann Example</article></body></html>'
    client = FakeClient(
        {"https://ex.gov/list": listing, "https://ex.gov/cases/A7": DETAIL},
    )
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert client.requested == ["https://ex.gov/list", "https://ex.gov/cases/A7"]
    assert result.detail_paths == ["detail_1.html"]


def test_a_contact_link_inside_a_record_is_not_its_detail_page(tmp_path: Path) -> None:
    # Teaser blocks carry a tip-line mailto next to (or instead of) a case link.
    # A mailto: is not a page to GET, so the pattern fallback owns this record.
    listing = '<html><body><article data-case-id="A7">Ann Example'
    listing += '<a href="mailto:tips@ex.gov">email us</a></article></body></html>'
    client = FakeClient({"https://ex.gov/list": listing, "https://ex.gov/cases/A7": DETAIL})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert client.requested == ["https://ex.gov/list", "https://ex.gov/cases/A7"]


def test_a_record_id_cannot_restructure_the_detail_url(tmp_path: Path) -> None:
    # The id comes out of the page's own markup, so an id carrying a separator
    # would otherwise walk the pattern's URL somewhere the pattern never pointed.
    listing = '<html><body><article data-case-id="A/../7">Ann Example</article></body></html>'
    client = FakeClient({"https://ex.gov/list": listing, "https://ex.gov/cases/A%2F..%2F7": DETAIL})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert client.requested[-1] == "https://ex.gov/cases/A%2F..%2F7"


def test_a_record_with_neither_a_link_nor_an_id_gets_no_detail_page(tmp_path: Path) -> None:
    # Nothing fills the pattern's {id}, and a URL with the placeholder still in it
    # is a 404 per record, not a detail page.
    listing = "<html><body><article>Ann Example</article></body></html>"
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert client.requested == ["https://ex.gov/list"]
    assert result.detail_paths == []
    assert result.records[0].detail_url is None


def test_no_detail_fetch_when_the_source_has_no_detail_pages(tmp_path: Path) -> None:
    # Records link somewhere, and the fake would serve those links. What says this
    # source has no detail pages is the Scout finding no detail_url_pattern.
    pages = {"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2}
    pages.update({f"https://ex.gov/cases/{i}": DETAIL for i in (1, 2, 3)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.detail_paths == []
    assert not any("/cases/" in u for u in client.requested)


def test_no_detail_fetch_when_no_field_lives_on_a_detail_page(tmp_path: Path) -> None:
    # A detail_url_pattern alone is not a reason to spend requests on detail pages.
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    candidate = _candidate(
        fields={"victim_name": FieldSpec(present=True, location=Location.NARRATIVE, page=Page.LIST)}
    )

    result = capture_html(candidate, client, s, tmp_path, tmp_path / "fx")

    assert result.detail_paths == []
    assert not any("/cases/" in u for u in client.requested)


# --- fixtures stay inside the fixture directory ---


def test_refuses_a_manifest_path_that_escapes_the_fixture_directory(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    sess.record(
        s,
        tmp_path,
        path="../../etc/passwd",
        url="https://ex.gov/list",
        status=200,
        body=b"x",
    )
    client = FakeClient({"https://ex.gov/list": LISTING_1})

    with pytest.raises(UnsafeFixturePath, match="etc/passwd"):
        capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")


def test_refuses_a_sibling_directory_that_shares_the_fixture_prefix(tmp_path: Path) -> None:
    # A string-prefix containment check passes "fx/../fxevil" because the escaped
    # path still starts with the fixture root's own characters. Containment has to
    # be a path-component walk, not a startswith.
    evil = tmp_path / "fxevil"
    evil.mkdir()
    (evil / "x.html").write_text("<html><body>not ours</body></html>", encoding="utf-8")
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    sess.record(
        s, tmp_path, path="../fxevil/x.html", url="https://ex.gov/list", status=200, body=b"x"
    )
    client = FakeClient({"https://ex.gov/list": LISTING_1})

    with pytest.raises(UnsafeFixturePath, match="fxevil"):
        capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")


def test_refuses_an_absolute_manifest_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.html"
    outside.write_text("<html><body>not ours</body></html>", encoding="utf-8")
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    sess.record(s, tmp_path, path=str(outside), url="https://ex.gov/list", status=200, body=b"x")
    client = FakeClient({"https://ex.gov/list": LISTING_1})

    with pytest.raises(UnsafeFixturePath):
        capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")


# --- what lands on disk and in the manifest ---


def test_fixtures_land_under_the_fixture_root_and_hash_into_the_manifest(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fixtures_root"] == "fx"
    assert [f["path"] for f in manifest["fixtures"]] == ["listing_1.html", "listing_2.html"]
    landed = tmp_path / "fx" / "listing_1.html"
    assert landed.read_bytes() == LISTING_1.encode()
    assert manifest["fixtures"][0]["sha256"] == hashlib.sha256(LISTING_1.encode()).hexdigest()


def test_records_key_by_listing_page_and_position(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert [r.key for r in result.records] == [
        "listing_1.html#0",
        "listing_1.html#1",
        "listing_2.html#0",
    ]
    assert "Ann Example" in result.records[0].payload


# --- pagination reporting ---


def test_pagination_names_the_kind_and_the_selector_that_found_it(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.pagination_kind == "query_param"
    assert result.pagination_detail == "a.next"


def test_a_single_page_listing_reports_no_pagination(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/list": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.pagination_kind == "single"
    assert result.pagination_detail is None
    assert result.listing_paths == ["listing_1.html"]
    assert result.truncated is False
    assert result.records_total == 1


def test_a_next_link_pointing_back_at_a_seen_page_terminates_the_walk(tmp_path: Path) -> None:
    loop = '<html><body><a class="case" href="/cases/1">A</a>'
    loop += '<a class="next" href="/list">Next</a></body></html>'
    client = FakeClient({"https://ex.gov/list": loop})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.listing_paths == ["listing_1.html"]
    # A page whose next link is itself may be a listing that ends here with a
    # disabled next, or the front of a cycle. Reporting a census would be a guess.
    assert result.truncated is True
    assert result.records_total is None


def test_a_pager_that_cycles_back_is_not_a_census(tmp_path: Path) -> None:
    # Page 2 links back at page 1, so pages 3 and 4 are never reached. Half the
    # source, reported as captured == total, becomes Task 11's exact-count
    # invariant — a fake invariant every generated parser satisfies.
    def page(number: int, next_href: str) -> str:
        body = "<html><body>"
        for offset in (0, 1):
            case = number * 2 - 1 + offset
            body += f'<a class="case" href="/cases/{case}">Case {case}</a>'
        return body + f'<a class="next" href="{next_href}">Next</a></body></html>'

    client = FakeClient(
        {
            "https://ex.gov/list": page(1, "/list?page=2"),
            "https://ex.gov/list?page=2": page(2, "/list"),  # back to the start
            "https://ex.gov/list?page=3": page(3, "/list?page=4"),
            "https://ex.gov/list?page=4": page(4, "/list?page=5"),
        }
    )
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert client.requested == ["https://ex.gov/list", "https://ex.gov/list?page=2"]
    assert result.records_captured == 4  # of the source's eight
    assert result.truncated is True
    assert result.records_total is None


# --- what counts as a record, and what counts as a next page ---


def test_a_fragment_next_link_is_not_a_next_page(tmp_path: Path) -> None:
    # Listings mark the current page with href="#", which resolves straight back to
    # the page it was found on. The walk has to stop there rather than count it.
    page = '<html><body><a class="case" href="/cases/1">A</a>'
    page += '<a class="next" href="#">Next</a></body></html>'
    client = FakeClient({"https://ex.gov/list": page})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert client.requested == ["https://ex.gov/list"]
    assert result.pagination_kind == "single"


def test_a_record_wrapped_in_a_block_is_counted_once(tmp_path: Path) -> None:
    # a.case and article both match this markup. Only the first selector to match
    # anything wins the page, or every case is counted twice and the record-count
    # invariant a later task generates is double what the site holds.
    page = '<html><body><article><a class="case" href="/cases/1">Ann</a></article>'
    page += '<article><a class="case" href="/cases/2">Bob</a></article></body></html>'
    client = FakeClient({"https://ex.gov/list": page})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2


def test_a_resumed_capture_decodes_a_page_exactly_as_the_first_run_did(tmp_path: Path) -> None:
    # The response object offers .text only on a fresh fetch, so decoding through it
    # would let a resumed run disagree with the run it resumed about what the page
    # says. Here .text is deliberately wrong: the bytes are what was captured.
    body = '<html><body><a class="case" href="/1">Ann\u00e9</a></body></html>'

    class LyingClient(FakeClient):
        def get(self, url: str) -> FakeResponse:
            self.requested.append(url)
            return FakeResponse(
                text="<html>WRONG</html>", status_code=200, content=body.encode("cp1252")
            )

    client = LyingClient({"https://ex.gov/list": body})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    first = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")
    second = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert "Ann\u00e9" in first.records[0].payload
    assert second.records[0].payload == first.records[0].payload


def test_an_html_listing_defines_its_own_record_list(tmp_path: Path) -> None:
    # A listing's records are whatever the selector matched on the source's own
    # pages, so the question Task 6's embedded shape has to leave open does not
    # arise here. If this came back False, every HTML capture would look like one
    # whose record list was never identified and route to an operator for nothing.
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.record_list_identified is True


def test_capture_html_satisfies_the_shape_protocol() -> None:
    # Task 6's capture_json binds to the same five positional parameters.
    shape: ShapeCapture = capture_html
    assert shape is capture_html


# --- the resume pairing property only separates on a THIRD run ---


def _five_case_listing() -> str:
    rows = "".join(f'<a class="case" href="/cases/{i}">Case {i}</a>' for i in range(1, 6))
    return f"<html><body>{rows}</body></html>"


def _five_case_pages() -> dict[str, str]:
    pages = {"https://ex.gov/list": _five_case_listing()}
    pages.update(
        {f"https://ex.gov/cases/{i}": f"<html><body>CASE {i}</body></html>" for i in range(1, 6)}
    )
    return pages


def test_every_sampled_record_carries_its_own_detail_page_across_three_runs(
    tmp_path: Path,
) -> None:
    # Two runs cannot show this: the collision guard hands a resumed URL back the
    # very name it was recorded under, so reading "the name this run invented"
    # accidentally reads the right file. It takes a third run, by which point
    # replace-by-URL has orphaned fixtures no manifest entry names any more — and
    # the invented name lands on one of those orphans, which holds another case.
    client = FakeClient(_five_case_pages())
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=3)
    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=5)
    after_two = len(client.requested)
    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=5)

    # Reading the invented name finds an orphan whose bytes fail the manifest's
    # digest, so the capture re-fetches a page it already holds. That wasted request
    # is the visible half; the mis-pairing it would otherwise be is the other half,
    # and only the digest check standing behind this one keeps it from happening.
    assert len(client.requested) == after_two
    detailed = [r for r in result.records if r.page == "detail"]
    assert len(detailed) == 5
    for position, record in enumerate(detailed, start=1):
        assert record.key == f"listing_1.html#{position - 1}"
        assert f"CASE {position}" in record.payload


# --- the manifest and the result describe one corpus ---


def test_a_page_the_walk_no_longer_reaches_leaves_the_manifest(tmp_path: Path) -> None:
    # records_total becomes an exact-count invariant, so a manifest holding listing
    # fixtures this walk never visited would let a later pass re-parse more records
    # than the count it is checking against.
    client = FakeClient(_five_case_pages())
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    sess.record(
        s, tmp_path, path="listing_9.html", url="https://ex.gov/list?page=9", status=200, body=b"x"
    )

    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=1)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    urls = {f["url"] for f in manifest["fixtures"]}
    assert "https://ex.gov/list?page=9" not in urls
    assert urls == {"https://ex.gov/list", "https://ex.gov/cases/1"}
    assert result.records_total == 5


def test_detail_fixtures_for_records_still_in_the_listing_are_kept(tmp_path: Path) -> None:
    # Pruning is scoped to URLs the corpus no longer contains. A detail page outside
    # this run's narrower sample is still a page of this source, so a later widening
    # must not have to re-fetch it.
    client = FakeClient(_five_case_pages())
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=5)
    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=2)
    after = len(client.requested)
    capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=5)

    assert len(client.requested) == after


# --- a pager that never admits it is finished ---


class Pager:
    """A paged listing. ``next_on_empty`` decides whether it admits it is finished."""

    def __init__(self, pages_with_records: int, *, next_on_empty: bool) -> None:
        self.pages_with_records = pages_with_records
        self.next_on_empty = next_on_empty
        self.requested: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.requested.append(url)
        if len(self.requested) > 20:
            raise AssertionError(f"runaway listing walk: {len(self.requested)} requests")
        page = int(url.partition("page=")[2] or 1)
        has_records = page <= self.pages_with_records
        body = "<html><body>"
        if has_records:
            body += f'<a class="case" href="/cases/{page}">Case {page}</a>'
        if has_records or self.next_on_empty:
            body += f'<a class="next" href="/list?page={page + 1}">Next</a>'
        body += "</body></html>"
        return FakeResponse(text=body, status_code=200, content=body.encode())


def test_the_walk_stops_at_the_first_page_that_yields_no_records(tmp_path: Path) -> None:
    client = Pager(pages_with_records=3, next_on_empty=True)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert len(result.listing_paths) == 4  # three with records, then the empty one
    assert result.records_captured == 3
    assert len(client.requested) == 4
    # It stopped while the pager was still offering more, so it is not a census.
    assert result.truncated is True
    assert result.records_total is None


def test_a_pager_that_admits_it_is_finished_still_reports_a_census(tmp_path: Path) -> None:
    client = Pager(pages_with_records=3, next_on_empty=False)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 3
    assert result.records_total == 3
    assert result.truncated is False


def test_a_page_that_parses_to_nothing_but_links_on_is_not_a_census(tmp_path: Path) -> None:
    # An outage notice or an interstitial in the middle of a listing parses to no
    # records while still linking the page after it. The walk has to stop — it
    # cannot tell this from the end of a pager — but a count that stops two records
    # short of the source becomes Task 11's exact-count invariant, and the pruned
    # manifest would agree with it, so nothing downstream could ever notice.
    pages = {
        "https://ex.gov/list": (
            '<html><body><a class="case" href="/cases/1">Ann</a>'
            '<a class="case" href="/cases/2">Bob</a>'
            '<a class="next" href="/list?page=2">Next</a></body></html>'
        ),
        "https://ex.gov/list?page=2": (
            '<html><body><div class="outage">temporarily unavailable</div>'
            '<a class="next" href="/list?page=3">Next</a></body></html>'
        ),
        "https://ex.gov/list?page=3": (
            '<html><body><a class="case" href="/cases/3">Cal</a>'
            '<a class="case" href="/cases/4">Dee</a></body></html>'
        ),
    }
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert client.requested == ["https://ex.gov/list", "https://ex.gov/list?page=2"]
    assert result.records_captured == 2  # two of the source's four
    assert result.truncated is True
    assert result.records_total is None


# --- nothing parsed is not a census of zero ---


def test_a_listing_that_parses_to_nothing_reports_an_unknown_total(tmp_path: Path) -> None:
    # captured == total is what marks a census downstream, so a total of zero would
    # become an exact-count invariant of zero that any parser passes.
    client = FakeClient({"https://ex.gov/list": "<html><body><p>nothing here</p></body></html>"})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 0
    assert result.records_total is None
    assert result.listing_paths == ["listing_1.html"]


def test_a_list_wrapped_in_one_article_is_not_a_census_of_one(tmp_path: Path) -> None:
    # <article> is the generic wrapper in the vocabulary, so it is tried last: a
    # page-level wrapper would otherwise swallow every row into a single record.
    rows = "".join(f'<li class="case"><a href="/cases/{i}">Case {i}</a></li>' for i in range(1, 13))
    listing = f"<html><body><article><ul>{rows}</ul></article></body></html>"
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 12
    assert result.records_total == 12


def test_rows_outside_the_vocabulary_inside_one_article_are_not_a_census_of_one(
    tmp_path: Path,
) -> None:
    """The hazard the ``article``-last ordering exists for, with the ordering unable to help.

    The sibling test above builds its rows as ``li.case``, which an EARLIER selector
    matches, so it pins the ordering rather than the hazard. Here the rows are
    ``div.case-row`` — outside the vocabulary entirely — so the generic fallback is the
    only hit and returns the wrapper as ONE record. Twelve rows became ``captured=1
    total=1``, i.e. ``assert found == 1`` against a twelve-record listing, and the
    inventory endorsed it: ``select_one`` over the wrapper payload scores every locator
    1/1, so the floors looked real and the run resolved PASS.
    """
    rows = "".join(
        f'<div class="case-row"><a href="/cases/{i}">Case {i}</a></div>' for i in range(1, 13)
    )
    listing = f"<html><body><article><h1>Cold cases</h1>{rows}</article></body></html>"
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 1
    assert result.records_total is None
    assert result.record_list_identified is False
    assert result.record_list_basis == "wrapped"


def test_a_single_article_that_really_is_the_only_record_still_refuses_the_census(
    tmp_path: Path,
) -> None:
    """One <article> is one <article>, and nothing in the markup says which it is.

    Refusing here costs a census on a one-record listing, which is the cheap direction:
    the alternative is claiming one on the twelve-record listing above.
    """
    listing = '<html><body><article><a href="/cases/1">Only case</a></article></body></html>'
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_total is None
    assert result.record_list_identified is False


def test_a_wrapper_beside_a_sidebar_promo_is_still_not_a_census_of_two(
    tmp_path: Path,
) -> None:
    """The nearest neighbour of the document above, and the reason counting matches fails.

    The detector used to require the generic fallback to have matched EXACTLY ONE node,
    which closed the reproduced page and left this one open: a theme that emits
    ``<article>`` for a sidebar promo -- which is what ``<article>`` is for -- makes it
    two matches, and a 12-record listing came back ``captured=2 total=2 basis=named``.
    ``select_one`` over the wrapper still scores every locator 1/1, so the floors do not
    object either.
    """
    rows = "".join(f'<div class="case-row"><a href="/c/{i}">Case {i}</a></div>' for i in range(12))
    listing = (
        f"<html><body><article>{rows}</article>"
        '<article class="promo"><h2>Submit a tip</h2></article></body></html>'
    )
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.records_total is None
    assert result.record_list_identified is False
    assert result.record_list_basis == "wrapped"


def test_articles_as_records_lose_their_census_too_and_that_is_the_accepted_cost(
    tmp_path: Path,
) -> None:
    """A listing whose records really are ``<article>`` is refused, deliberately.

    Nothing in the markup separates five record articles from a wrapper plus four theme
    blocks, so the condition is which selector won rather than how many nodes it
    returned. The rows are still captured; only the count is withheld, and
    ``--accept-partial unidentified`` clears it. An ``<article>``-per-record listing that
    also marks its records (``article.case``) is matched by ``li.case``/``a.case``'s
    siblings long before the fallback is reached.
    """
    rows = "".join(f'<article><a href="/cases/{i}">Case {i}</a></article>' for i in range(1, 6))
    client = FakeClient({"https://ex.gov/list": f"<html><body>{rows}</body></html>"})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 5
    assert result.records_total is None
    assert result.record_list_identified is False


def test_a_named_record_selector_still_earns_its_census_beside_theme_articles(
    tmp_path: Path,
) -> None:
    """The fallback is only reached when every specific selector missed.

    This is what keeps the widened condition from costing the ordinary case: a listing
    whose rows carry the source's own record markup never reaches ``article`` at all,
    however many ``<article>`` elements the theme puts on the page.
    """
    rows = "".join(f'<li class="case"><a href="/cases/{i}">Case {i}</a></li>' for i in range(1, 6))
    listing = (
        f'<html><body><article class="promo">tip line</article><ul>{rows}</ul>'
        "<article>footer</article></body></html>"
    )
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 5
    assert result.records_total == 5
    assert result.record_list_identified is True


# --- a pager this module cannot follow is not the end of the listing ---


def test_a_pager_outside_the_next_vocabulary_refuses_the_census(tmp_path: Path) -> None:
    """``a.pagination__next`` is a real next link that ``_next_link`` cannot see.

    It used to end the walk exactly as "there is no next page" does: ``captured=2
    total=2 truncated=False`` on page 1 of n, and ``assert found == 2`` against a
    paginated source.
    """
    listing = (
        '<html><body><a class="case" href="/cases/1">A</a>'
        '<a class="case" href="/cases/2">B</a>'
        '<a class="pagination__next" href="/list?page=2">Next</a></body></html>'
    )
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


@pytest.mark.parametrize(
    "pager",
    [
        '<a class="pagination-next" href="/list?page=2">Next</a>',
        '<a aria-label="Next page" href="/list?page=2">&gt;</a>',
        '<li class="next"><a href="/list?page=2">go</a></li>',
        '<a href="/list?page=2">Next &rsaquo;</a>',
        '<a href="/list?page=2">\u00bb</a>',
        '<div class="pagination"><a href="/list?page=2">2</a></div>',
    ],
)
def test_every_shape_of_unfollowable_pager_refuses_the_census(tmp_path: Path, pager: str) -> None:
    listing = f'<html><body><a class="case" href="/cases/1">A</a>{pager}</body></html>'
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.truncated is True
    assert result.records_total is None


def test_a_page_that_parses_to_nothing_beside_an_unfollowable_pager_is_truncated(
    tmp_path: Path,
) -> None:
    listing = (
        "<html><body><p>temporarily unavailable</p>"
        '<a class="pagination__next" href="/list?page=2">Next</a></body></html>'
    )
    client = FakeClient({"https://ex.gov/list": listing})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 0
    assert result.truncated is True


def test_a_finished_drupal_pager_still_earns_its_census(tmp_path: Path) -> None:
    """The false positive the third pass of _more_on_offer is scoped to avoid.

    The last page of a walked pager links BACKWARD — to "1", to "First" — and page one
    was entered at the bare index URL rather than at the URL the pager gives it, so
    those links resolve outside ``seen``. A numbered-pager check that ran here would
    refuse the census on every correctly finished listing.
    """
    page1 = (
        '<html><body><a class="case" href="/cases/1">A</a>'
        '<ul class="pager"><li class="pager__item--next"><a href="/list?page=1">Next</a></li></ul>'
        "</body></html>"
    )
    page2 = (
        '<html><body><a class="case" href="/cases/2">B</a>'
        '<ul class="pager">'
        '<li class="pager__item--first"><a href="/list?page=0">First</a></li>'
        '<li class="pager__item"><a href="/list?page=0">1</a></li>'
        "</ul></body></html>"
    )
    client = FakeClient({"https://ex.gov/list": page1, "https://ex.gov/list?page=1": page2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.truncated is False
    assert result.records_total == 2


# --- fixtures land where the manifest says they do ---


def test_refuses_a_fixture_directory_the_session_did_not_record(tmp_path: Path) -> None:
    # LISTING_2 has no next link, so without the guard this capture would SUCCEED
    # and the test would fail as DID NOT RAISE — the guard is what it measures.
    client = FakeClient({"https://ex.gov/list": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    with pytest.raises(FixtureRootMismatch, match="fx"):
        capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path / "other")


def test_an_empty_fixtures_root_means_beside_the_manifest(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/list": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x")

    result = capture_html(_candidate(detail_url_pattern=None), client, s, tmp_path, tmp_path)

    assert result.listing_paths == ["listing_1.html"]
    assert (tmp_path / "listing_1.html").is_file()


# --- the detail sample is a sample of what can be fetched ---


def test_records_without_a_link_do_not_burn_sample_slots(tmp_path: Path) -> None:
    # Half the rows carry no link. Skipping them mid-sample would halve the
    # denominator the detail coverage floor is computed over.
    rows = ""
    for i in range(1, 7):
        inner = f'<a href="/cases/{i}">Case {i}</a>' if i % 2 else f"Case {i}"
        rows += f'<li class="case">{inner}</li>'
    pages = {"https://ex.gov/list": f"<html><body><ul>{rows}</ul></body></html>"}
    pages.update({f"https://ex.gov/cases/{i}": DETAIL for i in (1, 3, 5)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx", detail_sample=2)

    assert len(result.detail_paths) == 2
    assert [u for u in client.requested if "/cases/" in u] == [
        "https://ex.gov/cases/1",
        "https://ex.gov/cases/5",
    ]


def test_two_records_pointing_at_one_detail_page_fetch_it_once(tmp_path: Path) -> None:
    # Fetching it twice would weight that page double in the same coverage
    # measurement, and name one fixture twice in detail_paths.
    listing = '<html><body><a class="case" href="/cases/1">Ann</a>'
    listing += '<a class="case" href="/cases/1">Ann again</a>'
    listing += '<a class="case" href="/cases/2">Bob</a></body></html>'
    pages = {"https://ex.gov/list": listing}
    pages.update({f"https://ex.gov/cases/{i}": DETAIL for i in (1, 2)})
    client = FakeClient(pages)
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")

    result = capture_html(_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.detail_paths == ["detail_1.html", "detail_2.html"]
    assert client.requested.count("https://ex.gov/cases/1") == 1
    assert [r.page for r in result.records] == ["detail", "list", "detail"]


# --- bytes are measured only after they are verified ---


def test_a_fixture_altered_between_runs_is_fetched_again(tmp_path: Path) -> None:
    # The manifest's sha256 exists to catch a fixture that changed on disk — a
    # line-ending rewrite, an editor, a partial restore. Reading it anyway would
    # measure bytes the capture never saw.
    client = FakeClient({"https://ex.gov/list": LISTING_1, "https://ex.gov/list?page=2": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    candidate = _candidate(detail_url_pattern=None)

    capture_html(candidate, client, s, tmp_path, tmp_path / "fx")
    tampered = tmp_path / "fx" / "listing_1.html"
    tampered.write_bytes(LISTING_1.replace("Ann Example", "Eve Evil").encode())
    result = capture_html(candidate, client, s, tmp_path, tmp_path / "fx")

    assert client.requested.count("https://ex.gov/list") == 2
    assert "Ann Example" in result.records[0].payload
    assert tampered.read_bytes() == LISTING_1.encode()


def test_a_digest_mismatch_says_so_before_re_fetching(tmp_path: Path, caplog: Any) -> None:
    # A fixture directory rewritten wholesale (a checkout under core.autocrlf, a
    # partial restore) fails every digest, and the conservative response — re-fetch —
    # silently re-crawls an entire rate-limited source. It has to be visible.
    client = FakeClient({"https://ex.gov/list": LISTING_2})
    s = sess.start(tmp_path, "html", now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")
    candidate = _candidate(detail_url_pattern=None)

    capture_html(candidate, client, s, tmp_path, tmp_path / "fx")
    (tmp_path / "fx" / "listing_1.html").write_bytes(LISTING_2.replace("\n", "\r\n").encode())
    with caplog.at_level(logging.WARNING):
        capture_html(candidate, client, s, tmp_path, tmp_path / "fx")

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("listing_1.html" in m and "https://ex.gov/list" in m for m in warnings)
