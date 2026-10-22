"""Schema-shape contracts for the C2 correlation response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from casesignal.correlation.schemas import (
    CorrelatedCaseSummary,
    MatchedDimension,
)


def test_matched_dimension_constructs_with_required_fields() -> None:
    d = MatchedDimension(name="weapon", value="firearm", low_confidence=False, weight=1.0)
    assert d.name == "weapon"
    assert d.value == "firearm"
    assert d.low_confidence is False
    assert d.weight == 1.0


def test_matched_dimension_low_confidence_is_required_bool() -> None:
    with pytest.raises(ValidationError):
        MatchedDimension(name="weapon", value="firearm", weight=1.0)  # type: ignore


def test_matched_dimension_weight_is_required() -> None:
    with pytest.raises(ValidationError):
        MatchedDimension(name="weapon", value="firearm", low_confidence=False)  # type: ignore


def test_correlated_case_summary_full_shape() -> None:
    summary = CorrelatedCaseSummary(
        case_id=42,
        slug="jane-doe-richmond-va-1992",
        victim_primary_name="Jane Doe",
        city="Richmond",
        state="VA",
        year=1992,
        score=2.5,
        score_max=3.5,
        proximity_factor=0.8,
        matched_dimensions=[
            MatchedDimension(name="weapon", value="firearm", low_confidence=False, weight=1.0),
            MatchedDimension(name="victim_gender", value="F", low_confidence=False, weight=0.5),
            MatchedDimension(name="victim_age", value="34 & 36", low_confidence=False, weight=0.5),
        ],
        distance_miles=12.4,
        years_apart=8,
    )
    assert summary.case_id == 42
    assert len(summary.matched_dimensions) == 3


def test_correlated_case_summary_allows_null_victim_name_and_city() -> None:
    summary = CorrelatedCaseSummary(
        case_id=99,
        slug="x",
        victim_primary_name=None,
        city=None,
        state="VA",
        year=2001,
        score=1.5,
        score_max=3.5,
        proximity_factor=1.0,
        matched_dimensions=[
            MatchedDimension(name="victim_gender", value="F", low_confidence=False, weight=0.5),
            MatchedDimension(name="victim_race", value="W", low_confidence=False, weight=0.5),
            MatchedDimension(name="victim_age", value="24 & 27", low_confidence=False, weight=0.5),
        ],
        distance_miles=3.0,
        years_apart=2,
    )
    assert summary.victim_primary_name is None
    assert summary.city is None


def test_correlated_case_summary_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CorrelatedCaseSummary(
            case_id=1,
            slug="x",
            victim_primary_name=None,
            city="Richmond",
            state="VA",
            year=1990,
            score=2.0,
            score_max=3.5,
            proximity_factor=0.9,
            matched_dimensions=[],
            distance_miles=10.0,
            years_apart=5,
            extra_field="rejected",  # type: ignore
        )
