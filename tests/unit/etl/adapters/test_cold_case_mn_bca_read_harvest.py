"""Unit tests for the MN BCA harvest reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from casesignal.etl.adapters.cold_case_mn_bca.read_harvest import (
    HarvestError,
    HarvestRecord,
    parse_harvest,
)

_GOOD = [
    {
        "ContentType": "Unsolved Homicide",
        "NameFirst": "Alex",
        "NameMiddle": "Middle",
        "NameLast": "Exampleton",
        "NameSuffix": None,
        "Age": 42,
        "Date1": "11/17/2021",
        "DateOfBirth": "6/20/1979",
        "LocationCity": "Minneapolis",
        "LocationCounty": "Hennepin",
        "LocationState": "MN",
        "PDF": "/bca/unsolved-cases/UnsolvedCasesDocuments/Exampleton-Alex.pdf",
        "Picture1": "/bca/unsolved-cases/UnsolvedCasesImages/Exampleton-Alex.jpg",
        "Reward": None,
    },
    {
        "ContentType": "Unsolved Homicide",
        "NameFirst": "Michael",
        "NameMiddle": None,
        "NameLast": "Sampleton",
        "NameSuffix": None,
        "Age": 19,
        "Date1": "7/31/1988",
        "DateOfBirth": "8/8/1968",
        "LocationCity": None,
        "LocationCounty": None,
        "LocationState": None,
        "PDF": "/bca/unsolved-cases/UnsolvedCasesDocuments/Sampleton-Michael.pdf",
        "Picture1": "/bca/unsolved-cases/UnsolvedCasesImages/Sampleton-Michael.PNG",
        "Reward": None,
    },
]


def test_parse_good_harvest(tmp_path: Path) -> None:
    p = tmp_path / "h.json"
    p.write_text(json.dumps(_GOOD), encoding="utf-8")
    records = parse_harvest(p)
    assert len(records) == 2
    assert isinstance(records[0], HarvestRecord)


def test_source_case_id_synthesis(tmp_path: Path) -> None:
    p = tmp_path / "h.json"
    p.write_text(json.dumps(_GOOD), encoding="utf-8")
    records = parse_harvest(p)
    assert records[0].source_case_id == "mn-exampleton-alex-2021-11-17"
    # Null-location row still gets a stable id from name + date.
    assert records[1].source_case_id == "mn-sampleton-michael-1988-07-31"


def test_null_location_is_tolerated(tmp_path: Path) -> None:
    p = tmp_path / "h.json"
    p.write_text(json.dumps(_GOOD), encoding="utf-8")
    records = parse_harvest(p)
    assert records[1].location_city is None
    assert records[1].location_county is None


def test_empty_harvest_raises(tmp_path: Path) -> None:
    p = tmp_path / "h.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(HarvestError, match="empty"):
        parse_harvest(p)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    bad = [{"ContentType": "Unsolved Homicide", "NameFirst": "X"}]  # no PDF/Date1/NameLast
    p = tmp_path / "h.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(HarvestError, match="missing"):
        parse_harvest(p)


def test_non_homicide_rows_are_skipped(tmp_path: Path) -> None:
    rows = [*_GOOD, {**_GOOD[0], "ContentType": "Missing Person"}]
    p = tmp_path / "h.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    records = parse_harvest(p)
    assert len(records) == 2  # the Missing Person row dropped


def test_duplicate_source_case_id_raises(tmp_path: Path) -> None:
    rows = [_GOOD[0], dict(_GOOD[0])]  # identical name+date → identical id
    p = tmp_path / "h.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(HarvestError, match="duplicate"):
        parse_harvest(p)


def test_reward_is_parsed(tmp_path: Path) -> None:
    rows = [{**_GOOD[0], "Reward": 25000}]
    p = tmp_path / "h.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    records = parse_harvest(p)
    assert records[0].reward == 25000


def test_non_list_harvest_raises(tmp_path: Path) -> None:
    p = tmp_path / "h.json"
    p.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(HarvestError, match="array"):
        parse_harvest(p)
