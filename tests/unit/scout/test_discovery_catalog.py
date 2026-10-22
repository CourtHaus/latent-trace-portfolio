import json
from pathlib import Path

from casesignal.scout.discovery.catalog import parse_arcgis, parse_socrata
from casesignal.scout.models import Channel, Confidence

FIX = Path("tests/fixtures/scout")


def test_parse_socrata_sets_dataset_id_and_exact_count() -> None:
    payload = json.loads((FIX / "socrata_catalog.json").read_text())
    cands = parse_socrata(payload, seen=set())
    assert {c.dataset_id for c in cands} == {"ab12-cd34", "zz99-yy88", "no00-ct01"}
    first = next(c for c in cands if c.dataset_id == "ab12-cd34")
    assert first.channel == Channel.SOCRATA
    assert first.case_count is not None
    assert first.case_count.value == 87
    assert first.case_count.confidence == Confidence.EXACT
    assert first.page_type == "api_json"


def test_parse_socrata_missing_count_yields_none() -> None:
    payload = json.loads((FIX / "socrata_catalog.json").read_text())
    cands = parse_socrata(payload, seen=set())
    pending = next(c for c in cands if c.dataset_id == "no00-ct01")
    assert pending.case_count is not None
    assert pending.case_count.value is None
    assert pending.case_count.confidence is None


def test_parse_socrata_dedups_against_seen() -> None:
    payload = json.loads((FIX / "socrata_catalog.json").read_text())
    seen = {"ab12-cd34"}
    cands = parse_socrata(payload, seen)
    assert {c.dataset_id for c in cands} == {"zz99-yy88", "no00-ct01"}


def test_parse_arcgis_uses_item_id_and_record_count() -> None:
    payload = json.loads((FIX / "arcgis_hub.json").read_text())
    cands = parse_arcgis(payload, seen=set())
    assert cands[0].dataset_id == "hub-item-1"
    assert cands[0].case_count is not None
    assert cands[0].case_count.value == 42
    assert cands[0].channel == Channel.ARCGIS
    assert cands[0].page_type == "api_json"
