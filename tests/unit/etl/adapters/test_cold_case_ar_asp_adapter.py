"""Tests for the AR ASP adapter shell (entry assembly + zero-entry guard)."""

from __future__ import annotations

from typing import Any

from casesignal.etl.adapters.cold_case_ar_asp.adapter import (
    ColdCaseARASPAdapter,
    entry_from_detail,
)
from casesignal.etl.adapters.cold_case_ar_asp.scrape import ArDetailFields, ArPhoto, IndexEntry


def _detail(**overrides: object) -> ArDetailFields:
    base: dict[str, Any] = dict(
        age_text="76",
        race="White",
        sex="Female",
        date_label="death",
        date_text="January 14, 1991",
        cause="Strangulation",
        county="Washington",
        case_number="SYN-001",
        narrative="A narrative.",
        contact_text="Contact ASP Company D at (202) 555-0100.",
        contact_agency="ASP Company D",
        contact_phone="(202) 555-0100",
        photos=[ArPhoto(source_url="https://media.ark.org/dps/x.jpg", alt=None, filename_hint="x.jpg")],
    )
    base.update(overrides)
    return ArDetailFields(**base)


def test_entry_from_detail_shapes_raw_dict() -> None:
    ie = IndexEntry(
        slug="ada-ann-exampleton-example",
        url="https://dps.arkansas.gov/.../cold-cases/ada-ann-exampleton-example/",
        link_text="Ada Ann Exampleton Example",
    )
    e = entry_from_detail(ie, _detail())
    assert e["slug"] == "ada-ann-exampleton-example"
    assert e["case_name"] == "Ada Ann Exampleton Example"
    assert e["case_type"] == "homicide"
    assert e["case_number"] == "SYN-001"
    assert e["source_detail_url"] == ie.url
    assert e["photos"] == [
        {"source_url": "https://media.ark.org/dps/x.jpg", "alt": None, "filename_hint": "x.jpg"}
    ]


def test_entry_from_detail_missing_person() -> None:
    ie = IndexEntry(slug="robin-sampleton", url="https://x/cold-cases/robin-sampleton/", link_text="Robin Sampleton")
    e = entry_from_detail(ie, _detail(date_label="missing", cause=None))
    assert e["case_type"] == "missing_person"


def test_adapter_name() -> None:
    assert ColdCaseARASPAdapter.adapter_name == "cold_case_ar_asp"
