from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import session as sess
from casesignal.drafter.shapes import json_feed
from casesignal.drafter.shapes.base import ShapeCapture
from casesignal.drafter.shapes.fixtures import FixtureRootMismatch, UnsafeFixturePath
from casesignal.drafter.shapes.json_feed import capture_json
from casesignal.scout.models import Candidate, Channel, Level

SODA = "https://data.xx.gov/resource/abcd-1234.json?$order=:id"
ARC = "https://svc.xx.gov/FeatureServer/0/query?where=1%3D1&outFields=*&f=json"
ARC_COUNT = "https://svc.xx.gov/FeatureServer/0/query?where=1%3D1&f=json&returnCountOnly=true"


@dataclass(frozen=True)
class FakeResponse:
    text: str
    status_code: int
    content: bytes


class FakeClient:
    """A GET that only knows the pages it was given; anything else is a loud KeyError."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.requested.append(url)
        body = self.pages[url]
        return FakeResponse(text=body, status_code=200, content=body.encode())


def _soda(limit: int, offset: int) -> str:
    return f"{SODA}&$limit={limit}&$offset={offset}"


def _arc(count: int, offset: int) -> str:
    return f"{ARC}&resultRecordCount={count}&resultOffset={offset}"


def _rows(*ids: int) -> str:
    return json.dumps([{"id": i, "name": f"Case {i}"} for i in ids])


def _features(*ids: int, more: bool) -> str:
    return json.dumps(
        {
            "features": [{"attributes": {"OBJECTID": i}, "geometry": None} for i in ids],
            "exceededTransferLimit": more,
        }
    )


def _socrata_candidate(**over: Any) -> Candidate:
    base: dict[str, Any] = dict(
        id="abcd-1234",
        level=Level.STATE,
        state="XX",
        index_url="https://data.xx.gov/d/abcd-1234",
        channel=Channel.SOCRATA,
        dataset_id="abcd-1234",
    )
    base.update(over)
    return Candidate(**base)


def _arcgis_candidate(**over: Any) -> Candidate:
    base: dict[str, Any] = dict(
        id="svc.xx.gov/FeatureServer",
        level=Level.STATE,
        state="XX",
        index_url="https://svc.xx.gov/FeatureServer/0",
        channel=Channel.ARCGIS,
    )
    base.update(over)
    return Candidate(**base)


def _embedded_candidate(**over: Any) -> Candidate:
    base: dict[str, Any] = dict(
        id="xx__agency",
        level=Level.STATE,
        state="XX",
        index_url="https://ex.gov/cases",
        channel=Channel.WEB,
        page_type="embedded_json",
    )
    base.update(over)
    return Candidate(**base)


def _session(tmp_path: Path, shape: str) -> sess.CaptureSession:
    return sess.start(tmp_path, shape, now="2026-08-31T00:00:00Z", nonce="x", fixtures_root="fx")


# --- Socrata: page until a short page ---


def test_socrata_pages_until_short_page(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 3
    assert result.records_total == 3
    assert result.truncated is False
    assert result.pagination_kind == "soda_offset"
    assert result.listing_paths == ["page_1.json", "page_2.json"]


def test_socrata_stops_at_max_records_and_reports_a_sample(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3, 4)})
    s = _session(tmp_path, "socrata")

    result = capture_json(
        _socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=2
    )

    assert result.records_captured == 2
    # Stopping at the cap is not reaching the end: captured == total is what marks a
    # census downstream, and this walk never saw how much more the feed held.
    assert result.records_total is None
    assert result.truncated is True


def test_socrata_cap_is_honoured_exactly_by_clamping_the_page(tmp_path: Path) -> None:
    # A page_size that does not divide the cap would otherwise overshoot it, and the
    # fixture on disk would hold records the result never counted — a corpus a later
    # re-parse disagrees with. The last request asks only for what is left.
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(1, 2): _rows(3)})
    s = _session(tmp_path, "socrata")

    result = capture_json(
        _socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=3
    )

    assert result.records_captured == 3
    assert result.truncated is True
    assert result.records_total is None


def test_records_carry_serialized_json_payloads(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): json.dumps([{"id": 1, "name": "Ann"}])})
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert json.loads(result.records[0].payload)["name"] == "Ann"
    assert result.records[0].page == "list"
    assert result.records[0].detail_url is None


def test_records_key_by_page_and_position(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert [r.key for r in result.records] == ["page_1.json#0", "page_1.json#1", "page_2.json#0"]


def test_a_socrata_feed_that_serves_nothing_is_not_a_census_of_zero(tmp_path: Path) -> None:
    # A total of zero would become an exact-count invariant of zero that every
    # generated parser passes.
    client = FakeClient({_soda(2, 0): "[]"})
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 0
    assert result.records_total is None
    assert result.listing_paths == ["page_1.json"]


def test_a_socrata_error_envelope_mid_walk_is_not_the_end_of_the_feed(tmp_path: Path) -> None:
    # Socrata answers a bad request with a JSON object, not the array it serves rows
    # in. Reading that as "no more rows" would report half a feed as a census.
    client = FakeClient(
        {
            _soda(2, 0): _rows(1, 2),
            _soda(2, 2): json.dumps({"error": True, "message": "Query timed out"}),
        }
    )
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


def test_a_body_that_is_not_json_at_all_truncates_the_walk(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): "<html>502 Bad Gateway</html>"})
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


def test_rows_that_are_not_objects_are_not_quietly_dropped_into_a_census(
    tmp_path: Path,
) -> None:
    # A feed whose array holds scalars is not one this capture can measure. Keeping
    # the objects and calling the count a census would understate the corpus.
    client = FakeClient({_soda(4, 0): json.dumps([{"id": 1}, "surprise", {"id": 2}])})
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=4)

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


def test_a_socrata_candidate_without_a_dataset_id_pages_its_index_url(tmp_path: Path) -> None:
    url = "https://data.xx.gov/resource/other.json"
    client = FakeClient({f"{url}?$order=:id&$limit=2&$offset=0": _rows(1)})
    s = _session(tmp_path, "socrata")
    candidate = _socrata_candidate(dataset_id=None, index_url=url)

    result = capture_json(candidate, client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 1


def test_a_hostile_dataset_id_cannot_restructure_the_url_or_name_a_fixture(
    tmp_path: Path,
) -> None:
    # dataset_id is server-supplied. Percent-encoding keeps it one path segment, and
    # fixture names are counter-derived so it never reaches the filesystem at all.
    hostile = "../../../etc/passwd"
    encoded = "..%2F..%2F..%2Fetc%2Fpasswd"
    url = f"https://data.xx.gov/resource/{encoded}.json?$order=:id&$limit=2&$offset=0"
    client = FakeClient({url: _rows(1)})
    s = _session(tmp_path, "socrata")

    result = capture_json(
        _socrata_candidate(dataset_id=hostile), client, s, tmp_path, tmp_path / "fx", page_size=2
    )

    assert client.requested == [url]
    assert result.listing_paths == ["page_1.json"]
    assert (tmp_path / "fx" / "page_1.json").is_file()


# --- ArcGIS: exceededTransferLimit is the end-of-feed signal ---


def test_arcgis_honours_exceeded_transfer_limit(tmp_path: Path) -> None:
    client = FakeClient(
        {
            _arc(2, 0): _features(1, 2, more=True),
            _arc(2, 2): _features(3, more=False),
        }
    )
    s = _session(tmp_path, "arcgis")

    result = capture_json(_arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 3
    assert result.records_total == 3
    assert result.truncated is False
    assert result.pagination_kind == "arcgis_offset"


def test_arcgis_records_keep_the_whole_feature(tmp_path: Path) -> None:
    # Geometry is where plottability comes from, so a record is the feature rather
    # than its attributes bag.
    client = FakeClient({_arc(2, 0): _features(7, more=False)})
    s = _session(tmp_path, "arcgis")

    result = capture_json(_arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    payload = json.loads(result.records[0].payload)
    assert payload["attributes"]["OBJECTID"] == 7
    assert "geometry" in payload


def test_arcgis_stopped_at_the_cap_while_more_was_advertised_is_not_a_census(
    tmp_path: Path,
) -> None:
    client = FakeClient({_arc(2, 0): _features(1, 2, more=True)})
    s = _session(tmp_path, "arcgis")

    result = capture_json(
        _arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=2
    )

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


def test_a_truncated_arcgis_walk_takes_its_total_from_the_services_own_count(
    tmp_path: Path,
) -> None:
    # returnCountOnly is the one authoritative corpus size available here, and a
    # known total larger than the sample is what scopes record-level assertions.
    client = FakeClient(
        {
            _arc(2, 0): _features(1, 2, more=True),
            ARC_COUNT: json.dumps({"count": 900}),
        }
    )
    s = _session(tmp_path, "arcgis")

    result = capture_json(
        _arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=2
    )

    assert result.records_captured == 2
    assert result.records_total == 900
    assert result.truncated is True
    # The probe is metadata about the corpus, not a page of it.
    assert result.listing_paths == ["page_1.json"]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [f["url"] for f in manifest["fixtures"]] == [_arc(2, 0)]


def test_a_reported_count_can_never_manufacture_a_census(tmp_path: Path) -> None:
    # A service that reports exactly what the truncated walk holds would otherwise
    # turn captured == total back on, and a stopped-short capture would claim to be
    # the whole corpus.
    client = FakeClient(
        {
            _arc(2, 0): _features(1, 2, more=True),
            ARC_COUNT: json.dumps({"count": 2}),
        }
    )
    s = _session(tmp_path, "arcgis")

    result = capture_json(
        _arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=2
    )

    assert result.truncated is True
    assert result.records_total is None


def test_an_unreachable_count_endpoint_leaves_the_total_unknown(tmp_path: Path) -> None:
    # The probe is an optional enrichment. A service that refuses it must cost the
    # capture a total, never the capture itself.
    class Refusing(FakeClient):
        def get(self, url: str) -> FakeResponse:
            if "returnCountOnly" in url:
                raise RuntimeError("404 Not Found")
            return super().get(url)

    client = Refusing({_arc(2, 0): _features(1, 2, more=True)})
    s = _session(tmp_path, "arcgis")

    result = capture_json(
        _arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=2
    )

    assert result.records_captured == 2
    assert result.records_total is None
    assert result.truncated is True


def test_a_census_arcgis_walk_does_not_spend_a_count_request(tmp_path: Path) -> None:
    client = FakeClient({_arc(2, 0): _features(1, more=False)})
    s = _session(tmp_path, "arcgis")

    capture_json(_arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert client.requested == [_arc(2, 0)]


def test_an_arcgis_error_payload_is_not_the_end_of_the_layer(tmp_path: Path) -> None:
    client = FakeClient(
        {
            _arc(2, 0): _features(1, 2, more=True),
            _arc(2, 2): json.dumps({"error": {"code": 500, "message": "Unable to complete"}}),
        }
    )
    s = _session(tmp_path, "arcgis")

    result = capture_json(_arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


def test_an_offset_that_stops_advancing_terminates_the_walk(tmp_path: Path) -> None:
    # A layer that keeps claiming exceededTransferLimit while returning nothing
    # would page the same offset forever, every request a real rate-limited GET.
    client = FakeClient(
        {
            _arc(2, 0): _features(1, 2, more=True),
            _arc(2, 2): _features(more=True),
            ARC_COUNT: json.dumps({"count": 2}),
        }
    )
    s = _session(tmp_path, "arcgis")

    result = capture_json(_arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert client.requested.count(_arc(2, 2)) == 1
    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


def test_an_arcgis_index_url_already_ending_in_query_is_not_doubled(tmp_path: Path) -> None:
    client = FakeClient({_arc(2, 0): _features(1, more=False)})
    s = _session(tmp_path, "arcgis")
    candidate = _arcgis_candidate(index_url="https://svc.xx.gov/FeatureServer/0/query")

    result = capture_json(candidate, client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.records_captured == 1


# --- embedded JSON: one page, and the payload is its own census ---


def _page(payload: str) -> str:
    return f'<html><body><script type="application/json">{payload}</script></body></html>'


def test_embedded_json_inside_a_script_tag_is_a_census(tmp_path: Path) -> None:
    body = _page(json.dumps({"data": [{"id": 1}, {"id": 2}, {"id": 3}]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 3
    assert result.records_total == 3
    assert result.truncated is False
    assert result.pagination_kind == "single"
    assert result.listing_paths == ["page_1.html"]


def test_an_endpoint_that_serves_bare_json_needs_no_script_tag(tmp_path: Path) -> None:
    # The NH DOJ shape: a documents API whose body is the payload itself.
    body = json.dumps({"data": [{"fields": {"title": ["Exampleton"]}}]})
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 1
    assert json.loads(result.records[0].payload)["fields"]["title"] == ["Exampleton"]


def test_a_nested_payload_is_found_below_the_top_level(tmp_path: Path) -> None:
    body = _page(json.dumps({"props": {"pageProps": {"results": [{"id": 1}, {"id": 2}]}}}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.records_total == 2


def test_the_first_script_that_holds_records_wins(tmp_path: Path) -> None:
    body = (
        "<html><body>"
        "<script>var x = 1;</script>"
        '<script type="application/ld+json">{"@type": "WebPage"}</script>'
        '<script type="application/json">{"data": [{"id": 1}]}</script>'
        "</body></html>"
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 1
    assert json.loads(result.records[0].payload)["id"] == 1


def test_an_unrecognised_payload_shape_reports_an_unknown_total(tmp_path: Path) -> None:
    client = FakeClient({"https://ex.gov/cases": "<html><body><p>nothing</p></body></html>"})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 0
    assert result.records_total is None
    assert result.listing_paths == ["page_1.html"]
    # The case where the record list was most emphatically not identified must not be
    # the case that reports it was.
    assert result.record_list_identified is False


def test_an_embedded_payload_over_the_cap_reports_the_payloads_own_size(
    tmp_path: Path,
) -> None:
    # The whole payload is in hand, so the corpus size is known exactly even though
    # only part of it is captured. That is a scoped sample, not a census.
    body = _page(json.dumps({"data": [{"id": i} for i in range(10)]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(
        _embedded_candidate(), client, s, tmp_path, tmp_path / "fx", max_records=4
    )

    assert result.records_captured == 4
    assert result.records_total == 10
    assert result.truncated is True


def test_an_embedded_payload_that_exactly_fills_the_cap_is_still_a_census(
    tmp_path: Path,
) -> None:
    # Nothing was withheld: the payload ended where the cap did. Treating the
    # boundary as "over the cap" would take a complete capture and report it as a
    # corpus of unknown size, and with the default cap that is any source holding
    # exactly 5000 records.
    body = _page(json.dumps({"data": [{"id": i} for i in range(4)]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(
        _embedded_candidate(), client, s, tmp_path, tmp_path / "fx", max_records=4
    )

    assert result.records_captured == 4
    assert result.records_total == 4
    assert result.truncated is False


def test_an_unnamed_list_of_scalars_never_outranks_the_real_record_list(
    tmp_path: Path,
) -> None:
    # Neither key here is one of the known row keys, so finding the records is a
    # guess — the riskiest thing this module does, because a wrong guess produces a
    # confident count of the wrong list. A shallower array of facet strings must
    # lose to the deeper array of objects rather than win on depth alone.
    body = _page(json.dumps({"filters": ["Example", "Sampleton"], "listing": {"coldCases": [{"id": 1}]}}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 1
    assert json.loads(result.records[0].payload)["id"] == 1
    # Nothing in the document named this list, so the rows are captured and the
    # total is not claimed: a census off a guess is the invariant this refuses.
    assert result.records_total is None


def test_an_embedded_payload_holding_scalars_is_not_a_census(tmp_path: Path) -> None:
    body = _page(json.dumps({"data": [{"id": 1}, 2, {"id": 3}]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


# --- what lands on disk and in the manifest ---


def test_fixtures_land_under_the_fixture_root_and_hash_into_the_manifest(
    tmp_path: Path,
) -> None:
    first, second = _rows(1, 2), _rows(3)
    client = FakeClient({_soda(2, 0): first, _soda(2, 2): second})
    s = _session(tmp_path, "socrata")

    capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fixtures_root"] == "fx"
    assert [f["path"] for f in manifest["fixtures"]] == ["page_1.json", "page_2.json"]
    assert (tmp_path / "fx" / "page_1.json").read_bytes() == first.encode()
    assert manifest["fixtures"][0]["sha256"] == hashlib.sha256(first.encode()).hexdigest()


def test_refuses_a_fixture_directory_the_session_did_not_record(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1)})
    s = _session(tmp_path, "socrata")

    with pytest.raises(FixtureRootMismatch, match="fx"):
        capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "other", page_size=2)


def test_refuses_a_manifest_path_that_escapes_the_fixture_directory(tmp_path: Path) -> None:
    s = _session(tmp_path, "socrata")
    sess.record(s, tmp_path, path="../../etc/passwd", url=_soda(2, 0), status=200, body=b"[]")
    client = FakeClient({_soda(2, 0): _rows(1)})

    with pytest.raises(UnsafeFixturePath, match="etc/passwd"):
        capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)


def test_a_page_the_walk_no_longer_reaches_leaves_the_manifest(tmp_path: Path) -> None:
    # records_total becomes an exact-count invariant, so a manifest naming fixtures
    # this walk never visited would let a later pass re-parse more than it checks.
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})
    s = _session(tmp_path, "socrata")
    sess.record(s, tmp_path, path="page_9.json", url=_soda(2, 900), status=200, body=b"[]")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert {f["url"] for f in manifest["fixtures"]} == {_soda(2, 0), _soda(2, 2)}
    assert result.records_total == 3


# --- resume ---


def test_resume_skips_already_fetched_pages(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})
    s = _session(tmp_path, "socrata")

    capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)
    after_first = len(client.requested)
    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert len(client.requested) == after_first
    assert result.records_captured == 3


def test_a_fixture_name_another_url_holds_is_not_reused(tmp_path: Path) -> None:
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "page_2.json").write_bytes(b"stale")
    s = _session(tmp_path, "socrata")
    sess.record(s, tmp_path, path="page_2.json", url=_soda(2, 900), status=200, body=b"stale")
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.listing_paths == ["page_1.json", "page_3.json"]
    assert (tmp_path / "fx" / "page_2.json").read_bytes() == b"stale"


def test_resume_reads_the_path_the_url_was_originally_recorded_to(tmp_path: Path) -> None:
    # Run 1 is pushed off page_2.json by a stale manifest entry, so page two of the
    # feed lands in page_3.json and the stale entry is then pruned. Run 2 invents
    # page_2.json for that same URL — a name whose file still holds the stale bytes.
    # Reading the invented name instead of the recorded one pairs a record key with
    # another page's payload; the digest check turns that into a wasted re-fetch,
    # and asking the manifest for the path avoids both.
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "page_2.json").write_bytes(b"stale")
    s = _session(tmp_path, "socrata")
    sess.record(s, tmp_path, path="page_2.json", url=_soda(2, 900), status=200, body=b"stale")
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})

    capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)
    after_first = len(client.requested)
    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert len(client.requested) == after_first
    assert result.listing_paths == ["page_1.json", "page_3.json"]
    assert json.loads(result.records[2].payload)["id"] == 3


def test_refetches_when_the_recorded_fixture_is_gone(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})
    s = _session(tmp_path, "socrata")

    capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)
    (tmp_path / "fx" / "page_1.json").unlink()
    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert client.requested.count(_soda(2, 0)) == 2
    assert result.records_captured == 3


def test_a_fixture_altered_between_runs_is_fetched_again(tmp_path: Path) -> None:
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3)})
    s = _session(tmp_path, "socrata")

    capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)
    tampered = tmp_path / "fx" / "page_1.json"
    tampered.write_bytes(json.dumps([{"id": 99, "name": "Eve Evil"}]).encode())
    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert client.requested.count(_soda(2, 0)) == 2
    assert json.loads(result.records[0].payload)["name"] == "Case 1"
    assert tampered.read_bytes() == _rows(1, 2).encode()


def test_a_digest_mismatch_says_so_before_re_fetching(tmp_path: Path, caplog: Any) -> None:
    client = FakeClient({_soda(2, 0): _rows(1)})
    s = _session(tmp_path, "socrata")

    capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)
    (tmp_path / "fx" / "page_1.json").write_bytes(_rows(1).encode() + b"\n")
    with caplog.at_level(logging.WARNING):
        capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("page_1.json" in m and _soda(2, 0) in m for m in warnings)


def test_a_resumed_capture_decodes_a_page_exactly_as_the_first_run_did(tmp_path: Path) -> None:
    # .text exists only on a fresh fetch, so decoding through it would let a resumed
    # run disagree with the run it resumed about what the feed said.
    body = json.dumps([{"id": 1, "name": "Anné"}])

    class LyingClient(FakeClient):
        def get(self, url: str) -> FakeResponse:
            self.requested.append(url)
            return FakeResponse(text="[]", status_code=200, content=body.encode("cp1252"))

    client = LyingClient({_soda(2, 0): body})
    s = _session(tmp_path, "socrata")

    first = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)
    second = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert json.loads(first.records[0].payload)["name"] == "Anné"
    assert second.records[0].payload == first.records[0].payload


# --- finding the record list is a search, and a census needs it to be a certainty ---


def test_a_shallow_unrelated_array_does_not_beat_the_feeds_own_data_list(
    tmp_path: Path,
) -> None:
    # The __NEXT_DATA__ shape. Running the generic fallback at depth 0 before
    # descending would pick the nav menu, capture two links, and report them as a
    # census of two — an exact-count invariant a parser that scrapes nav links
    # satisfies, with the three real cases never captured at all.
    body = _page(
        json.dumps(
            {
                "nav": [{"href": "/a"}, {"href": "/b"}],
                "wrapper": {"data": [{"case": 1}, {"case": 2}, {"case": 3}]},
            }
        )
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 3
    assert [json.loads(r.payload)["case"] for r in result.records] == [1, 2, 3]
    # One named candidate in the whole document, so this census is earned.
    assert result.records_total == 3
    assert result.truncated is False


def test_a_bare_json_array_document_is_its_own_census(tmp_path: Path) -> None:
    # The commonest JSON shape of all: an endpoint that answers with the array
    # itself. There is no document to search and nothing to choose between, so this
    # is a census with no guessing behind it — the one embedded find that is
    # authoritative without a row key naming it.
    client = FakeClient({"https://ex.gov/cases": json.dumps([{"id": 1}, {"id": 2}])})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.records_total == 2
    assert result.truncated is False


def test_a_record_list_wrapped_in_an_array_is_still_found_by_name(tmp_path: Path) -> None:
    # A named search that only descends through objects never sees this list and
    # falls to the guess, which answers with the one-element wrapper: a census of 1.
    body = _page(json.dumps({"a": [{"data": [{"case": 1}, {"case": 2}]}]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert [json.loads(r.payload)["case"] for r in result.records] == [1, 2]
    assert result.records_total == 2


def test_two_named_candidates_capture_rows_but_decline_the_census(tmp_path: Path) -> None:
    # `items` is a known row key and here it is the filter dropdown, while the real
    # cases sit under `data` two levels down. Nothing in the document settles which
    # is the corpus, so neither can this: the rows are still captured, and the count
    # is not allowed to become an exact-count invariant.
    body = _page(
        json.dumps(
            {
                "items": [{"label": "All counties"}, {"label": "Unsolved"}],
                "props": {"pageProps": {"data": [{"case_id": 1}, {"case_id": 2}, {"case_id": 3}]}},
            }
        )
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.records_total is None
    # Not truncated: nothing stopped short. The size of the corpus is simply not a
    # thing this document established.
    assert result.truncated is False


def test_a_single_named_candidate_still_earns_its_census(tmp_path: Path) -> None:
    # The other half of the rule: declining ambiguous censuses must not cost the
    # unambiguous ones, or the embedded shape never reports a total at all.
    body = _page(json.dumps({"meta": {"generated": "2026-08-31"}, "data": [{"id": 1}, {"id": 2}]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 2
    assert result.records_total == 2
    assert result.truncated is False


def test_an_over_cap_payload_found_by_guess_reports_no_total(tmp_path: Path) -> None:
    # The payload's own length is the size of the corpus only if this list IS the
    # corpus. Off a guess it is just the length of something.
    body = _page(json.dumps({"listing": {"coldCases": [{"id": i} for i in range(10)]}}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(
        _embedded_candidate(), client, s, tmp_path, tmp_path / "fx", max_records=4
    )

    assert result.records_captured == 4
    assert result.records_total is None
    assert result.truncated is True


def test_a_script_that_names_its_records_beats_an_earlier_one_that_does_not(
    tmp_path: Path,
) -> None:
    # Document order decides among equals only. A framework blob higher up the head
    # whose record list can only be guessed at must not displace the payload the page
    # was actually rendered from, or the census goes to the wrong script.
    body = (
        "<html><body>"
        '<script type="application/json">{"catalog": [{"slug": "a"}, {"slug": "b"}]}</script>'
        '<script type="application/json">{"data": [{"case_id": 1}]}</script>'
        "</body></html>"
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 1
    assert json.loads(result.records[0].payload)["case_id"] == 1
    assert result.records_total == 1


# --- the configured cap bounds the capture, not the response size ---


def test_a_socrata_server_that_ignores_the_requested_limit_is_still_capped(
    tmp_path: Path,
) -> None:
    # $limit is a request, not a guarantee: a view with a server-side override, or a
    # proxy in front of one, answers with whatever it likes. Accepting that is a
    # server-chosen bound on what this capture holds in memory and writes to disk.
    client = FakeClient({_soda(2, 0): _rows(*range(1, 11))})
    s = _session(tmp_path, "socrata")

    result = capture_json(
        _socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=4
    )

    assert result.records_captured == 2
    assert client.requested == [_soda(2, 0)]
    assert result.truncated is True
    assert result.records_total is None


def test_an_arcgis_layer_that_overruns_result_record_count_is_still_capped(
    tmp_path: Path,
) -> None:
    client = FakeClient({_arc(2, 0): _features(*range(1, 11), more=True), ARC_COUNT: "{}"})
    s = _session(tmp_path, "arcgis")

    result = capture_json(
        _arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2, max_records=4
    )

    assert result.records_captured == 2
    assert result.truncated is True
    assert result.records_total is None


# --- a body the walk rejected is not a page of the corpus ---


def test_a_socrata_error_envelope_leaves_the_manifest_and_the_result(tmp_path: Path) -> None:
    # The manifest is what a later pass re-parses. An error envelope left in it sits
    # on disk beside the real pages and gets read as one of them.
    client = FakeClient(
        {_soda(2, 0): _rows(1, 2), _soda(2, 2): json.dumps({"error": True, "message": "boom"})}
    )
    s = _session(tmp_path, "socrata")

    result = capture_json(_socrata_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.listing_paths == ["page_1.json"]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [f["url"] for f in manifest["fixtures"]] == [_soda(2, 0)]
    assert result.records_captured == 2
    assert result.truncated is True


def test_an_arcgis_error_payload_leaves_the_manifest_and_the_result(tmp_path: Path) -> None:
    client = FakeClient(
        {
            _arc(2, 0): _features(1, 2, more=True),
            _arc(2, 2): json.dumps({"error": {"code": 500}}),
            ARC_COUNT: "{}",
        }
    )
    s = _session(tmp_path, "arcgis")

    result = capture_json(_arcgis_candidate(), client, s, tmp_path, tmp_path / "fx", page_size=2)

    assert result.listing_paths == ["page_1.json"]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [f["url"] for f in manifest["fixtures"]] == [_arc(2, 0)]
    assert result.records_captured == 2
    assert result.truncated is True


# --- a search that hit its bounds is not evidence of how many candidates exist ---


def _budget_payload(filler: int) -> str:
    """A nav menu, a wall of filler, and the real cases behind it.

    Two named candidates, so the honest answer is "no census" — but the filler is
    what decides whether the width bound truncates the level the second candidate
    lives on, and a truncation that leaves one survivor looks exactly like a
    document that only ever named one.
    """
    return _page(
        json.dumps(
            {
                "a": {"items": [{"href": "/county"}, {"href": "/year"}]},
                "filler": [{"pad": i} for i in range(filler)],
                "z": {"data": [{"case_id": i} for i in range(300)]},
            }
        )
    )


@pytest.mark.parametrize("filler", [5, 600])
def test_the_width_bound_cannot_turn_two_candidates_into_a_census(
    tmp_path: Path, filler: int
) -> None:
    # The identical document either side of the bound. Slicing the level before the
    # named scan drops the `data` subtree at 600, leaves `items` as the only
    # survivor, and stamps the nav menu authoritative: a census of two links with
    # three hundred real cases never seen. The bound must cost a census, never
    # invent one.
    client = FakeClient({"https://ex.gov/cases": _budget_payload(filler)})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_total is None
    assert result.record_list_identified is False


@pytest.mark.parametrize(
    ("filler", "identified"),
    [(5, True), (600, False)],
)
def test_a_lone_candidate_found_before_a_width_cut_is_not_authoritative(
    tmp_path: Path, filler: int, identified: bool
) -> None:
    # The other half of the width bound, and the half the nav-menu payload does not
    # reach: here the named search DOES find its one candidate, and only afterwards
    # runs out of budget with a subtree unscanned. Nothing in that subtree is a rival
    # — the filler objects carry no row key at all — which is the point. Declining is
    # not about what is down there, it is about not having looked.
    body = _page(
        json.dumps(
            {
                "data": [{"c": i} for i in range(3)],
                "filler": [{"pad": i} for i in range(filler)],
            }
        )
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 3
    assert result.record_list_identified is identified
    assert result.records_total == (3 if identified else None)


@pytest.mark.parametrize(
    ("tail_depth", "identified"),
    [(2, True), (8, False)],
)
def test_a_lone_candidate_found_above_a_depth_cut_is_not_authoritative(
    tmp_path: Path, tail_depth: int, identified: bool
) -> None:
    # Same property through the other bound. A document deeper than the search goes
    # has structure the search never read, so its one candidate is not evidence that
    # the document only ever named one.
    tail: Any = {"pad": 1}
    for _ in range(tail_depth):
        tail = {"x": tail}
    body = _page(json.dumps({"data": [{"c": i} for i in range(3)], "tail": tail}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 3
    assert result.record_list_identified is identified
    assert result.records_total == (3 if identified else None)


@pytest.mark.parametrize(
    ("outer", "inner", "extra"),
    [("items", "cases", "section"), ("results", "data", "page"), ("data", "items", "group")],
)
def test_a_group_wrapper_is_not_a_census_of_one(
    tmp_path: Path, outer: str, inner: str, extra: str
) -> None:
    # An embedded-paginated shape: the named outer list holds ONE wrapper object, and
    # the real cases hang off that wrapper. Skipping the descent on the row key alone
    # hides the inner list from the named search, so the document looks singly named
    # and is stamped authoritative — a census of one wrapper object with a hundred-odd
    # cases a level below it, never counted, and the identification flag now actively
    # asserting that this was the record list.
    body = _page(json.dumps({outer: [{extra: "A", inner: [{"case_id": i} for i in range(120)]}]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_total is None
    assert result.record_list_identified is False


@pytest.mark.parametrize(
    "document",
    [
        # The inner list is NOT under a row key, so descending into the wrapper finds no
        # rival and the outer list of one is still the only contender.
        {"data": [{"page": 1, "entries": [{"case_id": i} for i in range(120)]}]},
        # The inner list is one object further down, so a one-level scan of the
        # element's own values sees a dict and calls the outer list records.
        {"data": [{"page": {"cases": [{"case_id": i} for i in range(120)]}}]},
        # __NEXT_DATA__: the same shape with the framework's wrappers above it.
        {
            "props": {
                "pageProps": {
                    "data": [{"section": {"items": [{"case_id": i} for i in range(120)]}}]
                }
            }
        },
    ],
)
def test_a_group_wrapper_is_refused_even_when_the_inner_key_is_not_in_the_vocabulary(
    tmp_path: Path, document: dict[str, Any]
) -> None:
    """The three wrapper shapes the parametrised sibling above cannot reach.

    That test walks row keys for BOTH the outer and the inner list, so it passes through
    RECORD_LIST_AMBIGUOUS — two named contenders — rather than through the wrapper guard
    it was written to pin. Each document here defeats that route in a different way, and
    each used to come back ``(1, True, 'named')``: an authoritative census of one wrapper
    with a hundred and twenty cases underneath it, uncounted.
    """
    client = FakeClient({"https://ex.gov/cases": _page(json.dumps(document))})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_total is None
    assert result.record_list_identified is False


def test_a_short_list_wrapping_a_longer_one_is_named_as_wrapped_not_ambiguous(
    tmp_path: Path,
) -> None:
    """The basis is the operator's next move, so a wrapper must not read as a rival."""
    document = {"data": [{"page": 1, "entries": [{"case_id": i} for i in range(120)]}]}
    client = FakeClient({"https://ex.gov/cases": _page(json.dumps(document))})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.record_list_basis == "wrapped"


# --- an embedded payload's own envelope ---


def test_a_paginated_json_endpoint_is_not_a_census_of_its_first_page(tmp_path: Path) -> None:
    """The most dangerous of the false censuses, because the rows are real records.

    ``_embedded_payload`` tries ``json.loads(body)`` first and ``capture.route`` sends
    any WEB candidate whose page_type mentions JSON here, so this sub-shape covers plain
    JSON endpoints — and plain JSON endpoints paginate. 50 real rows beside a stated
    total of 307 used to come back ``captured=50 total=50 truncated=False``: locators
    match, coverage is real, the floors are real, and the exact-count invariant asserts
    50 against a 307-record source.
    """
    body = json.dumps(
        {
            "totalCount": 307,
            "page": 1,
            "pageSize": 50,
            "next": "/api/cases?page=2",
            "data": [{"case_id": i} for i in range(50)],
        }
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 50
    assert result.truncated is True
    assert result.records_total == 307


@pytest.mark.parametrize(
    "envelope",
    [
        {"next": "/api/cases?page=2"},
        {"nextPage": "https://ex.gov/api/cases?page=2"},
        {"has_more": True},
        {"hasNextPage": True},
        {"totalCount": 307},
        {"numberMatched": 307},
    ],
)
def test_every_envelope_that_says_there_is_more_refuses_the_census(
    tmp_path: Path, envelope: dict[str, Any]
) -> None:
    document = {**envelope, "data": [{"case_id": i} for i in range(50)]}
    client = FakeClient({"https://ex.gov/cases": json.dumps(document)})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.truncated is True
    assert result.records_total != result.records_captured


@pytest.mark.parametrize(
    "envelope",
    [
        {"next": None},
        {"next": ""},
        {"has_more": False},
        {"totalCount": 3},
        {"count": 3},
    ],
)
def test_an_envelope_that_says_this_is_all_of_it_keeps_the_census(
    tmp_path: Path, envelope: dict[str, Any]
) -> None:
    """Every way a feed emits the key while saying the page is the last one."""
    document = {**envelope, "data": [{"case_id": i} for i in range(3)]}
    client = FakeClient({"https://ex.gov/cases": json.dumps(document)})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.truncated is False
    assert result.records_total == 3


@pytest.mark.parametrize(
    ("label", "document"),
    [
        (
            "json:api",
            {
                "data": [{"case_id": i} for i in range(50)],
                "links": {"next": "/api/cases?page=2"},
                "meta": {"total": 307},
            },
        ),
        (
            "hal",
            {
                "_links": {"next": {"href": "/api/cases?page=2"}},
                "data": [{"c": i} for i in range(50)],
            },
        ),
        (
            "meta block",
            {"meta": {"totalCount": 307, "nextPage": 2}, "data": [{"c": i} for i in range(50)]},
        ),
        (
            "meta.pagination",
            {"meta": {"pagination": {"total": 307}}, "data": [{"c": i} for i in range(50)]},
        ),
        ("page count", {"page": 1, "pages": 7, "data": [{"c": i} for i in range(50)]}),
        ("full page", {"offset": 0, "limit": 50, "data": [{"c": i} for i in range(50)]}),
        ("string total", {"totalCount": "307", "data": [{"c": i} for i in range(50)]}),
        ("float total", {"totalCount": 307.0, "data": [{"c": i} for i in range(50)]}),
    ],
)
def test_the_standard_paginated_envelopes_are_not_censuses_of_page_one(
    tmp_path: Path, label: str, document: dict[str, Any]
) -> None:
    """The reproduced document was closed; the class it belongs to was not.

    Reading only the top-level object covered `{"totalCount": …, "next": …}` and missed
    JSON:API and HAL -- between them, the paginated-JSON conventions -- because both put
    the pointer and the total one level down under `links`/`_links`/`meta`. Each row here
    came back `captured=50 total=50 truncated=False`: fifty real records, real locators,
    real coverage, and `assert found == 50` against a 307-record source.
    """
    client = FakeClient({"https://ex.gov/cases": json.dumps(document)})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 50
    assert result.truncated is True
    assert result.records_total != 50


@pytest.mark.parametrize(
    ("label", "document"),
    [
        # The closed set is what keeps a document scan from reading this as pagination.
        ("nav menu", {"nav": {"next": "/about"}, "data": [{"case_id": i} for i in range(3)]}),
        # JSON:API's own way of saying "this is the last page".
        (
            "json:api last page",
            {
                "data": [{"c": i} for i in range(3)],
                "links": {"next": None, "self": "/x"},
                "meta": {"total": 3},
            },
        ),
        ("one page of pages", {"page": 1, "pages": 1, "data": [{"c": i} for i in range(3)]}),
        # A page size the rows did NOT fill is the clearest statement of a last page.
        ("room left in the page", {"limit": 1000, "data": [{"c": i} for i in range(3)]}),
    ],
)
def test_an_envelope_block_that_says_this_is_the_last_page_keeps_the_census(
    tmp_path: Path, label: str, document: dict[str, Any]
) -> None:
    client = FakeClient({"https://ex.gov/cases": _page(json.dumps(document))})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.truncated is False
    assert result.records_total == 3


@pytest.mark.parametrize("size", [3000, 5000])
def test_a_large_plain_feed_is_still_walked_past_rather_than_into(size: int) -> None:
    """The wrapper scan's node budget must sit above the record count, not below it.

    The first level of that scan is the named list's own elements. A budget under the
    record count runs out on every large feed, reports the scan incomplete, and voids
    the census of a genuine 5,000-record payload -- which is precisely the outcome the
    skip in `_descend` exists to protect, arrived at by the guard meant to sharpen it.
    """
    document = {"data": [{"id": i, "name": f"Case {i}"} for i in range(size)]}
    found = json_feed._rows(document)

    assert found is not None
    assert len(found.rows) == size
    assert found.authoritative is True
    assert found.basis == "named"


def test_a_record_carrying_a_nested_array_still_earns_its_census(tmp_path: Path) -> None:
    # The other side of the wrapper test, and the reason it is a judgement rather than
    # a rule: a record with its own small array of objects reads as a wrapper, so the
    # search descends into a list it did not need to. That is affordable here and the
    # census survives; when it is not affordable the cost is the census, never a false
    # one.
    body = _page(
        json.dumps({"data": [{"case_id": i, "aliases": [{"name": "x"}]} for i in range(3)]})
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 3
    assert result.records_total == 3
    assert result.record_list_identified is True


def test_a_named_list_with_no_usable_rows_is_not_identified_after_a_width_cut(
    tmp_path: Path,
) -> None:
    # The named-FALLBACK branch: no candidate was plausible, so the answer is the one
    # named list even though it holds a scalar, and the width cut means the search
    # never learned whether another was named. It cannot produce a census either way,
    # so the only thing the guard protects is the flag — which three later tasks read.
    body = _page(json.dumps({"data": [{"id": 1}, 2], "filler": [{"pad": i} for i in range(900)]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 1
    assert result.records_total is None
    assert result.record_list_identified is False


def test_a_source_that_serves_nothing_is_not_a_source_nobody_read(tmp_path: Path) -> None:
    # Both come back with no records and no total, and they are different answers. The
    # first named where its records live and has none: a real reading of a real source.
    # The second never said where to look.
    served_nothing = _page(json.dumps({"data": []}))
    unreadable = _page(json.dumps({"title": "Cold cases", "count": 12}))

    outcomes = {}
    for name, body in (("served_nothing", served_nothing), ("unreadable", unreadable)):
        client = FakeClient({"https://ex.gov/cases": body})
        s = _session(tmp_path / name, "embedded_json")
        result = capture_json(
            _embedded_candidate(), client, s, tmp_path / name, tmp_path / name / "fx"
        )
        outcomes[name] = (
            result.records_captured,
            result.records_total,
            result.record_list_identified,
        )

    assert outcomes["served_nothing"] == (0, None, True)
    assert outcomes["unreadable"] == (0, None, False)


def test_a_large_feed_under_one_row_key_still_earns_its_census(tmp_path: Path) -> None:
    # The over-correction the width bound would otherwise cause. Descending into a
    # named list puts its own records on the next level, which exhausts the budget
    # and voids the authority the document had already established — so a perfectly
    # ordinary six-hundred-case feed would report no total.
    body = _page(json.dumps({"data": [{"case_id": i} for i in range(600)]}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 600
    assert result.records_total == 600
    assert result.record_list_identified is True


# --- only a list that could be records creates ambiguity ---


def test_an_empty_sibling_list_does_not_cost_the_census(tmp_path: Path) -> None:
    # `items` is a known row key and this one is empty, so it was never a possible
    # answer. Counting it as a rival candidate costs a real census and protects
    # nothing at all.
    body = _page(json.dumps({"data": [{"c": i} for i in range(4)], "meta": {"items": []}}))
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 4
    assert result.records_total == 4
    assert result.record_list_identified is True


def test_a_scalar_sibling_list_does_not_cost_the_census(tmp_path: Path) -> None:
    # Same again for a facet list of strings under `value`: disqualified as an
    # answer by the same test that disqualifies it as a guess.
    body = _page(
        json.dumps({"data": [{"c": i} for i in range(4)], "filters": {"value": ["Example", "Sampleton"]}})
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_captured == 4
    assert result.records_total == 4
    assert result.record_list_identified is True


def test_two_plausible_candidates_still_decline_the_census(tmp_path: Path) -> None:
    # The other half: filtering out the impossible candidates must not soften the
    # guard against two real ones.
    body = _page(
        json.dumps(
            {
                "items": [{"label": "All counties"}, {"label": "Unsolved"}],
                "props": {"pageProps": {"data": [{"case_id": 1}, {"case_id": 2}]}},
            }
        )
    )
    client = FakeClient({"https://ex.gov/cases": body})
    s = _session(tmp_path, "embedded_json")

    result = capture_json(_embedded_candidate(), client, s, tmp_path, tmp_path / "fx")

    assert result.records_total is None
    assert result.record_list_identified is False


# --- "we never found the record list" is reported, not inferred ---


def test_the_four_embedded_outcomes_are_distinguishable(tmp_path: Path) -> None:
    # Two of these are byte-identical in every other field, and they mean opposite
    # things: one is an operator's problem (we never worked out which list held the
    # records) and one is a parser's (we found the right list and it held junk).
    payloads = {
        "ambiguous_under_cap": {
            "items": [{"label": "a"}, {"label": "b"}],
            "props": {"pageProps": {"data": [{"c": 1}, {"c": 2}, {"c": 3}]}},
        },
        "guessed_over_cap": {"listing": {"coldCases": [{"id": i} for i in range(9)]}},
        "authoritative_over_cap": {"data": [{"id": i} for i in range(9)]},
        "scalar_inside_named": {"data": [{"id": 1}, 2, {"id": 3}]},
    }
    seen = {}
    for name, payload in payloads.items():
        client = FakeClient({"https://ex.gov/cases": _page(json.dumps(payload))})
        s = _session(tmp_path / name, "embedded_json")
        result = capture_json(
            _embedded_candidate(),
            client,
            s,
            tmp_path / name,
            tmp_path / name / "fx",
            max_records=3,
        )
        seen[name] = (result.records_total, result.truncated, result.record_list_identified)

    assert seen["ambiguous_under_cap"] == (None, False, False)
    assert seen["guessed_over_cap"] == (None, True, False)
    assert seen["authoritative_over_cap"] == (9, True, True)
    assert seen["scalar_inside_named"] == (None, True, True)
    # The pair the old result could not tell apart.
    assert seen["guessed_over_cap"] != seen["scalar_inside_named"]


def test_a_feed_defines_its_own_record_list(tmp_path: Path) -> None:
    # SODA serves an array of rows and an ArcGIS layer serves `features`; neither
    # leaves the question open, so neither may look like an unidentified capture.
    # A capped SODA sample is otherwise byte-identical to an embedded guess.
    client = FakeClient({_soda(2, 0): _rows(1, 2), _soda(2, 2): _rows(3, 4)})
    s = _session(tmp_path / "soda", "socrata")
    capped = capture_json(
        _socrata_candidate(),
        client,
        s,
        tmp_path / "soda",
        tmp_path / "soda" / "fx",
        page_size=2,
        max_records=2,
    )

    arc_client = FakeClient({_arc(2, 0): _features(1, more=False)})
    arc_s = _session(tmp_path / "arc", "arcgis")
    arc = capture_json(
        _arcgis_candidate(),
        arc_client,
        arc_s,
        tmp_path / "arc",
        tmp_path / "arc" / "fx",
        page_size=2,
    )

    assert (capped.records_total, capped.truncated) == (None, True)
    assert capped.record_list_identified is True
    assert arc.record_list_identified is True


def test_capture_json_satisfies_the_shape_protocol() -> None:
    shape: ShapeCapture = capture_json
    assert shape is capture_json
