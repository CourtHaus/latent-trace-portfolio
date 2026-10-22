"""Census Bureau geocoder client — JSON parsing + retry."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from casesignal.geocoding.census import CensusGeocoder, CensusResult


@pytest.fixture
def census() -> Any:
    c = CensusGeocoder(max_retries=2, timeout_seconds=1.0)
    yield c
    c.close()


def _response(
    status: int,
    json_body: dict[str, Any] | None = None,
    *,
    request_url: str = "https://example.test/",
) -> httpx.Response:
    if json_body is not None:
        return httpx.Response(
            status,
            json=json_body,
            request=httpx.Request("GET", request_url),
        )
    return httpx.Response(
        status,
        content=b"err",
        request=httpx.Request("GET", request_url),
    )


_HIT_PAYLOAD = {
    "result": {
        "addressMatches": [
            {
                "matchedAddress": "6000 BARSTOW RD, BALTIMORE, MD, 21206",
                "coordinates": {"x": -76.5388, "y": 39.3384},
            }
        ]
    }
}

_NO_MATCH_PAYLOAD: dict[str, Any] = {"result": {"addressMatches": []}}


def test_geocode_returns_match(census: Any) -> None:
    with patch.object(
        census._client,
        "get",
        return_value=_response(200, _HIT_PAYLOAD),
    ):
        result = census.geocode("6000 block of Barstow Rd", state_code="MD")

    assert isinstance(result, CensusResult)
    assert result.latitude == pytest.approx(39.3384)
    assert result.longitude == pytest.approx(-76.5388)
    assert "BARSTOW" in result.matched_address


def test_geocode_no_match_returns_none(census: Any) -> None:
    with patch.object(
        census._client,
        "get",
        return_value=_response(200, _NO_MATCH_PAYLOAD),
    ):
        result = census.geocode("nonexistent address xyz", state_code="MD")

    assert result is None


def test_geocode_appends_state_when_missing(census: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: Any, params: Any = None, **kwargs: Any) -> Any:
        captured["params"] = params
        return _response(200, _NO_MATCH_PAYLOAD)

    with patch.object(census._client, "get", side_effect=fake_get):
        census.geocode("100 Main St", state_code="MD")

    assert "MD" in captured["params"]["address"]


def test_geocode_does_not_double_append_state(census: Any) -> None:
    """If state_code is already in the input string, don't append again."""
    captured: dict[str, Any] = {}

    def fake_get(url: Any, params: Any = None, **kwargs: Any) -> Any:
        captured["params"] = params
        return _response(200, _NO_MATCH_PAYLOAD)

    with patch.object(census._client, "get", side_effect=fake_get):
        census.geocode("100 Main St, MD", state_code="MD")

    # The address was passed through; no double "MD"
    occurrences = captured["params"]["address"].upper().count("MD")
    assert occurrences == 1


def test_geocode_retries_on_5xx_then_succeeds(census: Any) -> None:
    responses = iter([_response(503), _response(200, _HIT_PAYLOAD)])

    with patch.object(
        census._client,
        "get",
        side_effect=lambda url, params=None, **kwargs: next(responses),
    ):
        result = census.geocode("6000 Barstow Rd", state_code="MD")

    assert result is not None


def test_geocode_returns_none_after_exhausting_retries(census: Any) -> None:
    with patch.object(
        census._client,
        "get",
        return_value=_response(503),
    ):
        result = census.geocode("anything", state_code="MD")

    assert result is None


def test_geocode_returns_none_on_transport_error(census: Any) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("network")

    with patch.object(census._client, "get", side_effect=boom):
        result = census.geocode("100 Main St", state_code="MD")

    assert result is None


def test_empty_address_returns_none(census: Any) -> None:
    assert census.geocode("", state_code="MD") is None
    assert census.geocode("   ", state_code="MD") is None
