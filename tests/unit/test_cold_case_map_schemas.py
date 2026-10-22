"""Pydantic schemas for GET /cold-cases/map — shape + nullability."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError


def test_item_accepts_null_incident_date_and_null_city() -> None:
    from casesignal.api.schemas.cold_cases import ColdCaseMapItem

    item = ColdCaseMapItem(
        case_id=1,
        slug="foo",
        source_case_id="src-1",
        case_name="Foo",
        case_type="homicide",
        incident_date=None,
        latitude=38.0,
        longitude=-78.0,
        state="VA",
        city=None,
        victim_primary_name=None,
        victim_genders=[],
        victim_races=[],
        geocode_precision=None,
        source_county_fips=None,
    )
    assert item.incident_date is None
    assert item.city is None


def test_item_round_trips_happy_path() -> None:
    from casesignal.api.schemas.cold_cases import ColdCaseMapItem

    item = ColdCaseMapItem(
        case_id=1,
        slug="foo",
        source_case_id="src-1",
        case_name="Foo",
        case_type="homicide",
        incident_date=date(2005, 7, 14),
        latitude=38.1234567,
        longitude=-78.1234567,
        state="VA",
        city="Charlottesville",
        victim_primary_name="Jane Doe",
        victim_genders=["F"],
        victim_races=["W"],
        geocode_precision="street",
        source_county_fips="51003",
    )
    assert item.model_dump(mode="json")["incident_date"] == "2005-07-14"
    assert item.model_dump(mode="json")["source_county_fips"] == "51003"


def test_item_rejects_extra_fields() -> None:
    from casesignal.api.schemas.cold_cases import ColdCaseMapItem

    with pytest.raises(ValidationError):
        ColdCaseMapItem.model_validate(
            {
                "case_id": 1,
                "slug": "foo",
                "source_case_id": "src-1",
                "case_name": "Foo",
                "case_type": "homicide",
                "incident_date": None,
                "latitude": 38.0,
                "longitude": -78.0,
                "state": "VA",
                "city": None,
                "victim_primary_name": None,
                "victim_genders": [],
                "victim_races": [],
                "geocode_precision": None,
                "extra_field": "bad",
            }
        )


def test_response_wraps_items_and_meta() -> None:
    from casesignal.api.schemas.cold_cases import (
        ColdCaseMapItem,
        ColdCaseMapMeta,
        ColdCaseMapResponse,
    )

    response = ColdCaseMapResponse(
        mode="points",
        data=[
            ColdCaseMapItem(
                case_id=1,
                slug="foo",
                source_case_id="src-1",
                case_name="Foo",
                case_type="homicide",
                incident_date=None,
                latitude=38.0,
                longitude=-78.0,
                state="VA",
                city=None,
                victim_primary_name=None,
                victim_genders=[],
                victim_races=[],
                geocode_precision=None,
            )
        ],
        meta=ColdCaseMapMeta(
            bbox=(-80.0, 36.0, -75.0, 40.0),
            returned=1,
            truncated=False,
            total_unfiltered=1,
        ),
    )
    dumped = response.model_dump(mode="json")
    assert dumped["mode"] == "points"
    assert dumped["data"][0]["case_id"] == 1
    assert dumped["clusters"] == []
    assert dumped["meta"]["bbox"] == [-80.0, 36.0, -75.0, 40.0]
    assert dumped["meta"]["truncated"] is False
