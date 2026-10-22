"""Tests for OK OSBI pure transform helpers."""

from __future__ import annotations

from typing import Any

from casesignal.etl.adapters.cold_case_ok_osbi.transform import (
    _split_display_name,
    assign_source_case_ids,
    map_case_type,
    normalize_ok_date,
    parse_contact,
)


def test_normalize_ok_date() -> None:
    assert normalize_ok_date("November 15, 1984") == "1984-11-15"
    assert normalize_ok_date("08/27/1980") == "1980-08-27"
    assert normalize_ok_date("December 2004") == "2004-12-01"
    assert normalize_ok_date("Unknown") is None
    assert normalize_ok_date(None) is None
    assert normalize_ok_date("sometime in the 90s") is None


def test_map_case_type() -> None:
    assert map_case_type("Homicide") == "homicide"
    assert map_case_type("Missing Person") == "missing_person"
    assert map_case_type("Suspicious Disappearance") == "missing_person"
    assert map_case_type("Suspicious Death") == "suspicious_death"
    assert map_case_type("Something New") == "cold_case"
    assert map_case_type(None) == "cold_case"


def test_map_case_type_tolerates_osbi_source_typos() -> None:
    # Real OSBI source defects observed in the live corpus (2026-07-08):
    # a bare "H" for Homicide (Jane (Sequoyah County) Doe) and a truncated
    # "Suspicious Disappearanc" missing its final 'e' (Deborah Joan Farmer).
    assert map_case_type("H") == "homicide"
    assert map_case_type("Suspicious Disappearanc") == "missing_person"
    # prefix tolerance shouldn't over-reach:
    assert map_case_type("Suspicious") == "cold_case"


def test_parse_contact_osbi_email() -> None:
    agency, email, phone = parse_contact(
        "For this invented example, please contact the OSBI via email cases@example.test"
    )
    assert email == "cases@example.test"
    assert phone is None


def test_parse_contact_local_pd_phone() -> None:
    agency, email, phone = parse_contact(
        "For this invented example, please contact the Duncan PD Crime Stoppers, phone (202) 555-0101"
    )
    assert phone == "(202) 555-0101"
    assert agency is not None and "Duncan" in agency


def test_parse_contact_none() -> None:
    assert parse_contact(None) == (None, None, None)


def test_split_display_name_suffix_aware() -> None:
    assert _split_display_name("James Middle Example") == ("James Middle", "Example")
    assert _split_display_name("Felix Bailey, Jr.") == ("Felix", "Bailey, Jr.")  # comma suffix
    assert _split_display_name("Mary Sampler") == ("Mary", "Sampler")


def test_split_display_name_non_comma_suffix() -> None:
    assert _split_display_name("John Smith Jr") == ("John", "Smith Jr")


def test_assign_source_case_ids_name_plus_date() -> None:
    entries: list[dict[str, Any]] = [
        {"name": "James Middle Example", "incident_date_iso": "1984-11-15"},
        {"name": "Mary Sampler", "incident_date_iso": None},
    ]
    assign_source_case_ids(entries)
    assert entries[0]["source_case_id"] == "james-middle-example-1984-11-15"
    assert entries[1]["source_case_id"] == "mary-sampler"


def test_assign_source_case_ids_dedup_suffix() -> None:
    entries: list[dict[str, Any]] = [
        {"name": "John Doe", "incident_date_iso": None},
        {"name": "John Doe", "incident_date_iso": None},
    ]
    assign_source_case_ids(entries)
    ids = {e["source_case_id"] for e in entries}
    assert len(ids) == 2  # collision resolved with a suffix


def test_assign_source_case_ids_dedup_namespace_collision() -> None:
    # "John Doe 1" (no date) slugifies to the same base id that the second
    # "John Doe" (no date) would collide-resolve to under a base-keyed
    # dedup namespace. A final-id-keyed namespace must still keep all
    # three distinct.
    entries: list[dict[str, Any]] = [
        {"name": "John Doe 1", "incident_date_iso": None},
        {"name": "John Doe", "incident_date_iso": None},
        {"name": "John Doe", "incident_date_iso": None},
    ]
    assign_source_case_ids(entries)
    ids = [e["source_case_id"] for e in entries]
    assert len(set(ids)) == 3
