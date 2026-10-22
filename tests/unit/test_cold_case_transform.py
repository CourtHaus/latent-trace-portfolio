"""Unit tests for cold_case_va transform helpers."""

from __future__ import annotations

from decimal import Decimal

from casesignal.etl.adapters.cold_case_va.transform import (
    _normalize_source_case_id,
    _nullify,
    _parse_date,
    _parse_weight,
    _parse_wkt_point,
)


class TestNormalizeSourceCaseId:
    def test_plain_numeric_id_passes_through(self) -> None:
        assert (
            _normalize_source_case_id("200410010237", "Chesterfield - 200410010237 - Someone")
            == "200410010237"
        )

    def test_hyphenated_id_passes_through(self) -> None:
        assert (
            _normalize_source_case_id("2022-0003209", "Augusta - 2022-0003209 - Someone")
            == "2022-0003209"
        )

    def test_scientific_notation_extracts_from_case_name(self) -> None:
        assert (
            _normalize_source_case_id(
                "2.0041E+11",
                "Chesterfield County - 200410010237 - Alex Exampleton",
            )
            == "200410010237"
        )

    def test_scientific_with_case_prefix_in_case_name(self) -> None:
        assert (
            _normalize_source_case_id(
                "1.99203E+11",
                "Richmond Police Department  - Case: 199203070012 - Robin Middle Sampleton",
            )
            == "199203070012"
        )

    def test_scientific_with_large_exponent(self) -> None:
        assert (
            _normalize_source_case_id(
                "8.10324E+12",
                "Fauquier County Sheriff's Office - Case: 8103240516752 - Alex Exampleton and Robin Sampleton",
            )
            == "8103240516752"
        )

    def test_lowercase_e_also_matched(self) -> None:
        assert (
            _normalize_source_case_id(
                "2.0041e11",
                "Chesterfield - 200410010237 - X",
            )
            == "200410010237"
        )

    def test_scientific_without_digits_in_case_name_returns_raw(self) -> None:
        # Fallback path: unable to repair, return raw so caller can log + continue.
        assert _normalize_source_case_id("2.0041E+11", "No digits here") == "2.0041E+11"

    def test_scientific_with_null_case_name_returns_raw(self) -> None:
        assert _normalize_source_case_id("2.0041E+11", None) == "2.0041E+11"

    def test_none_passes_through(self) -> None:
        assert _normalize_source_case_id(None, "anything") is None

    def test_empty_string_passes_through(self) -> None:
        assert _normalize_source_case_id("", "anything") == ""


def test_parse_wkt_point_valid() -> None:
    lat, lon = _parse_wkt_point("POINT (-79.00735 38.20302)")
    assert lon == Decimal("-79.00735")
    assert lat == Decimal("38.20302")


def test_parse_wkt_point_with_long_precision() -> None:
    lat, lon = _parse_wkt_point("POINT (-79.15577424284099 38.00436074691171)")
    assert lon == Decimal("-79.15577424284099")
    assert lat == Decimal("38.00436074691171")


def test_parse_wkt_point_empty_returns_none() -> None:
    assert _parse_wkt_point("") == (None, None)
    assert _parse_wkt_point(None) == (None, None)


def test_parse_wkt_point_malformed_returns_none() -> None:
    # We prefer returning (None, None) over raising, so one bad row doesn't
    # kill the whole ingestion.
    assert _parse_wkt_point("not a point") == (None, None)


def test_parse_date_us_mmddyyyy() -> None:
    parsed = _parse_date("12/22/1967")
    assert parsed is not None
    assert parsed.isoformat() == "1967-12-22"

    parsed = _parse_date("4/10/2018")
    assert parsed is not None
    assert parsed.isoformat() == "2018-04-10"


def test_parse_date_empty_returns_none() -> None:
    assert _parse_date("") is None
    assert _parse_date(None) is None


def test_parse_date_malformed_returns_none() -> None:
    assert _parse_date("unknown") is None
    assert _parse_date("2018-04-10") is None  # ISO format not expected; strict parser


def test_parse_weight_valid() -> None:
    assert _parse_weight("185") == 185
    assert _parse_weight("  185  ") == 185


def test_parse_weight_empty_returns_none() -> None:
    assert _parse_weight("") is None
    assert _parse_weight(None) is None


def test_parse_weight_non_numeric_returns_none() -> None:
    assert _parse_weight("unknown") is None
    assert _parse_weight("approx 185") is None


def test_nullify_blank() -> None:
    assert _nullify("") is None
    assert _nullify(None) is None
    assert _nullify("  ") is None
    assert _nullify("value") == "value"
    assert _nullify("  value  ") == "value"
