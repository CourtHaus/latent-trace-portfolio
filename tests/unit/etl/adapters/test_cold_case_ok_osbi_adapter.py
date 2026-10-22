"""Tests for the OK OSBI adapter shell (entry assembly + name/type mapping)."""

from __future__ import annotations

from casesignal.etl.adapters.cold_case_ok_osbi.adapter import (
    ColdCaseOKOSBIAdapter,
    entry_from_case,
)
from casesignal.etl.adapters.cold_case_ok_osbi.scrape import OkCase, OkPhoto


def _case(**over: object) -> OkCase:
    base = dict(
        name="James Middle Example",
        case_type_label="Homicide",
        date_text="November 15, 1984",
        narrative="On November 15, 1984 ... shot in the head.",
        contact_text="If you have any information ... cold.case@osbi.ok.gov",
        photo=OkPhoto(source_url="https://oklahoma.gov/x.jpg", alt="ADAMS_JAMES", filename_hint="ADAMS_JAMES.jpg"),
    )
    base.update(over)
    return OkCase(**base)  # type: ignore[arg-type]


def test_entry_from_case_shapes_dict() -> None:
    e = entry_from_case(_case())
    assert e["case_name"] == "James Middle Example"
    assert e["case_type"] == "homicide"
    assert e["incident_date_iso"] == "1984-11-15"
    assert e["date_text"] == "November 15, 1984"
    assert e["photo"] == {
        "source_url": "https://oklahoma.gov/x.jpg",
        "alt": "ADAMS_JAMES",
        "filename_hint": "ADAMS_JAMES.jpg",
    }


def test_entry_from_case_suspicious_death() -> None:
    e = entry_from_case(_case(case_type_label="Suspicious Death"))
    assert e["case_type"] == "suspicious_death"


def test_entry_from_case_no_photo() -> None:
    e = entry_from_case(_case(photo=None))
    assert e["photo"] is None


def test_adapter_name() -> None:
    assert ColdCaseOKOSBIAdapter.adapter_name == "cold_case_ok_osbi"
