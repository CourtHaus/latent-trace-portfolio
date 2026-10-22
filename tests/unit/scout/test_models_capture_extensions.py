"""SP2 contract extensions: measured coverage, locators, and the capture block."""

from pathlib import Path

from casesignal.scout.models import (
    Candidate,
    CaptureInfo,
    Channel,
    FieldSpec,
    Level,
    Location,
    LocatorKind,
    Page,
)
from casesignal.scout.registry import Registry


def test_field_spec_carries_measured_coverage_and_locator() -> None:
    spec = FieldSpec(
        present=True,
        location=Location.STRUCTURED,
        page=Page.DETAIL,
        coverage=0.92,
        locator="strong:contains('AGE:')",
        locator_kind=LocatorKind.CSS,
    )
    assert spec.coverage == 0.92
    assert spec.locator_kind is LocatorKind.CSS


def test_capture_block_round_trips_through_registry(tmp_path: Path) -> None:
    candidate = Candidate(
        id="ok__osbi",
        level=Level.STATE,
        state="OK",
        index_url="https://oklahoma.gov/osbi/cold-cases.html",
        channel=Channel.WEB,
        fields={"victim_age": FieldSpec(present=True, location=Location.NARRATIVE, coverage=0.4)},
        capture=CaptureInfo(
            session_id="20260831T140211Z-a3f9",
            shape="html",
            listing_pages=10,
            records_captured=307,
            records_total=307,
            pagination_kind="range_pages",
        ),
    )
    path = tmp_path / "registry.yaml"
    reg = Registry({}, [])
    reg.upsert(candidate)
    reg.save(path)

    loaded = Registry.load(path).get("ok__osbi")
    assert loaded is not None
    assert loaded.capture is not None
    assert loaded.capture.session_id == "20260831T140211Z-a3f9"
    assert loaded.capture.records_total == 307
    assert loaded.fields["victim_age"].coverage == 0.4


def test_registry_loads_pre_sp2_yaml_without_new_fields(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        "candidates:\n"
        "  ok__osbi:\n"
        "    id: ok__osbi\n"
        "    level: state\n"
        "    state: OK\n"
        "    index_url: https://example.gov/x\n"
        "    channel: web\n"
        "    fields:\n"
        "      victim_age:\n"
        "        present: true\n"
        "        location: narrative\n"
        "deferred: []\n"
    )
    loaded = Registry.load(path).get("ok__osbi")
    assert loaded is not None
    assert loaded.capture is None
    assert loaded.fields["victim_age"].coverage is None


def test_locator_kind_and_listing_record_count_round_trip(tmp_path: Path) -> None:
    candidate = Candidate(
        id="ok__osbi",
        level=Level.STATE,
        state="OK",
        index_url="https://oklahoma.gov/osbi/cold-cases.html",
        channel=Channel.WEB,
        fields={
            "victim_age": FieldSpec(
                present=True,
                location=Location.STRUCTURED,
                page=Page.DETAIL,
                coverage=0.92,
                locator="strong:contains('AGE:')",
                locator_kind=LocatorKind.CSS,
            )
        },
        capture=CaptureInfo(
            session_id="20260831T140211Z-a3f9",
            shape="socrata",
            listing_pages=4,
            records_captured=307,
            records_total=None,
            pagination_kind="offset",
            pagination_detail="$offset=0&$limit=100",
            transport="curl_cffi",
            fetched_at="2026-08-31T14:02:11Z",
            listing_record_count=411,
        ),
    )
    path = tmp_path / "registry.yaml"
    reg = Registry({}, [])
    reg.upsert(candidate)
    reg.save(path)

    loaded = Registry.load(path).get("ok__osbi")
    assert loaded is not None
    spec = loaded.fields["victim_age"]
    assert spec.locator == "strong:contains('AGE:')"
    assert spec.locator_kind is LocatorKind.CSS
    assert loaded.capture is not None
    assert loaded.capture.listing_record_count == 411
    assert loaded.capture.records_total is None
    assert loaded.capture.transport == "curl_cffi"
    assert loaded.capture.pagination_detail == "$offset=0&$limit=100"
    assert loaded.capture.fetched_at == "2026-08-31T14:02:11Z"


def test_capture_info_defaults_are_optional() -> None:
    info = CaptureInfo(session_id="s1", shape="html")
    assert info.listing_pages == 0
    assert info.records_captured == 0
    assert info.records_total is None
    assert info.listing_record_count == 0
    assert info.transport == "httpx"


def test_capture_block_with_explicit_nulls_falls_back_to_declared_defaults(
    tmp_path: Path,
) -> None:
    """A hand-edited registry may leave scalar capture keys empty (YAML null).

    Those fields are declared int/str, so an explicit null must resolve to the
    dataclass default rather than smuggling None past the type checker.
    """
    path = tmp_path / "registry.yaml"
    path.write_text(
        "candidates:\n"
        "  ok__osbi:\n"
        "    id: ok__osbi\n"
        "    level: state\n"
        "    state: OK\n"
        "    index_url: https://example.gov/x\n"
        "    channel: web\n"
        "    capture:\n"
        "      session_id: 20260831T140211Z-a3f9\n"
        "      shape: html\n"
        "      listing_pages:\n"
        "      records_captured:\n"
        "      transport:\n"
        "      listing_record_count:\n"
        "deferred: []\n"
    )
    loaded = Registry.load(path).get("ok__osbi")
    assert loaded is not None
    assert loaded.capture is not None
    assert loaded.capture.listing_pages == 0
    assert loaded.capture.records_captured == 0
    assert loaded.capture.transport == "httpx"
    assert loaded.capture.listing_record_count == 0


def test_field_spec_with_explicit_nulls_loads_without_raising(tmp_path: Path) -> None:
    """An explicit-null `locator_kind` must load as None, not raise on Enum coercion."""
    path = tmp_path / "registry.yaml"
    path.write_text(
        "candidates:\n"
        "  ok__osbi:\n"
        "    id: ok__osbi\n"
        "    level: state\n"
        "    state: OK\n"
        "    index_url: https://example.gov/x\n"
        "    channel: web\n"
        "    fields:\n"
        "      victim_age:\n"
        "        present: true\n"
        "        location: narrative\n"
        "        coverage:\n"
        "        locator:\n"
        "        locator_kind:\n"
        "deferred: []\n"
    )
    loaded = Registry.load(path).get("ok__osbi")
    assert loaded is not None
    spec = loaded.fields["victim_age"]
    assert spec.coverage is None
    assert spec.locator is None
    assert spec.locator_kind is None


def test_the_capture_verdict_fields_round_trip(tmp_path: Path) -> None:
    """`truncated` and `record_list_identified` are why a total is unknown.

    Persisting the unknown total without them loses the distinction between a walk
    that stopped short, a payload whose record list was never identified, and a
    source that simply has nothing to count.
    """
    candidate = Candidate(
        id="ok__osbi",
        level=Level.STATE,
        state="OK",
        index_url="https://oklahoma.gov/osbi/cold-cases.html",
        channel=Channel.WEB,
        capture=CaptureInfo(
            session_id="20260831T140211Z-a3f9",
            shape="embedded_json",
            records_captured=12,
            records_total=None,
            truncated=True,
            record_list_identified=False,
        ),
    )
    path = tmp_path / "registry.yaml"
    reg = Registry({}, [])
    reg.upsert(candidate)
    reg.save(path)

    loaded = Registry.load(path).get("ok__osbi")
    assert loaded is not None and loaded.capture is not None
    assert loaded.capture.truncated is True
    assert loaded.capture.record_list_identified is False


def test_the_capture_verdict_fields_default_when_absent_or_null(tmp_path: Path) -> None:
    """An older registry, and a hand-edited null, both read as the safe default."""
    assert CaptureInfo(session_id="s1", shape="html").truncated is False
    assert CaptureInfo(session_id="s1", shape="html").record_list_identified is True

    path = tmp_path / "registry.yaml"
    path.write_text(
        "candidates:\n"
        "  ok__osbi:\n"
        "    id: ok__osbi\n"
        "    level: state\n"
        "    state: OK\n"
        "    index_url: https://example.gov/x\n"
        "    channel: web\n"
        "    capture:\n"
        "      session_id: 20260831T140211Z-a3f9\n"
        "      shape: html\n"
        "      truncated:\n"
        "      record_list_identified:\n"
        "deferred: []\n"
    )
    loaded = Registry.load(path).get("ok__osbi")
    assert loaded is not None and loaded.capture is not None
    assert loaded.capture.truncated is False
    assert loaded.capture.record_list_identified is True
