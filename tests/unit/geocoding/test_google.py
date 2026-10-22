"""GoogleGeocoder client — env-gated, classifies location_type into tier."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest import MonkeyPatch

from casesignal.geocoding.google import GoogleGeocoder, GoogleResult


def _mock_response(*, status_code: int = 200, json_body: dict[str, Any] | None = None) -> Any:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    return response


def _payload(*, location_type: str, lat: float = 39.74, lon: float = -104.99) -> dict[str, Any]:
    return {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Test, CO, USA",
                "geometry": {
                    "location": {"lat": lat, "lng": lon},
                    "location_type": location_type,
                },
            }
        ],
    }


def test_from_env_returns_none_when_unset(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert GoogleGeocoder.from_env() is None


def test_from_env_returns_none_when_empty(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "")
    assert GoogleGeocoder.from_env() is None


def test_from_env_constructs_when_key_set(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake_test_key")
    g = GoogleGeocoder.from_env()
    assert g is not None
    g.close()


def test_constructor_rejects_empty_key() -> None:
    with pytest.raises(ValueError):
        GoogleGeocoder("")


@pytest.mark.parametrize(
    "location_type,expected_tier",
    [
        ("ROOFTOP", "street"),
        ("RANGE_INTERPOLATED", "street"),
        ("GEOMETRIC_CENTER", "landmark"),
        ("APPROXIMATE", "landmark"),
    ],
)
def test_location_type_classification(location_type: Any, expected_tier: Any) -> None:
    g = GoogleGeocoder("test_key")
    with patch.object(
        g._client,
        "get",
        return_value=_mock_response(json_body=_payload(location_type=location_type)),
    ):
        r = g.geocode("anything", state_code="CO")
    assert r is not None
    assert r.tier == expected_tier
    assert r.location_type == location_type
    g.close()


def test_zero_results_returns_none() -> None:
    g = GoogleGeocoder("test_key")
    with patch.object(
        g._client,
        "get",
        return_value=_mock_response(json_body={"status": "ZERO_RESULTS", "results": []}),
    ):
        r = g.geocode("nonsense", state_code="CO")
    assert r is None
    g.close()


def test_over_query_limit_returns_none() -> None:
    g = GoogleGeocoder("test_key")
    with patch.object(
        g._client,
        "get",
        return_value=_mock_response(json_body={"status": "OVER_QUERY_LIMIT"}),
    ):
        r = g.geocode("anything", state_code="CO")
    assert r is None
    g.close()


def test_request_denied_returns_none() -> None:
    """REQUEST_DENIED (e.g. invalid key) should not raise — surface a None."""
    g = GoogleGeocoder("bad_key")
    with patch.object(
        g._client,
        "get",
        return_value=_mock_response(json_body={"status": "REQUEST_DENIED"}),
    ):
        r = g.geocode("anything", state_code="CO")
    assert r is None
    g.close()


def test_appends_state_code_when_not_in_address() -> None:
    g = GoogleGeocoder("test_key")
    captured: dict[str, Any] = {}

    def fake_get(url: Any, params: Any = None, **kw: Any) -> Any:
        captured["params"] = params
        return _mock_response(json_body=_payload(location_type="ROOFTOP"))

    with patch.object(g._client, "get", side_effect=fake_get):
        g.geocode("Denver", state_code="CO")

    assert captured["params"]["address"] == "Denver, CO"
    g.close()


def test_does_not_double_append_state() -> None:
    g = GoogleGeocoder("test_key")
    captured = {}

    def fake_get(url: Any, params: Any = None, **kw: Any) -> Any:
        captured["params"] = params
        return _mock_response(json_body=_payload(location_type="ROOFTOP"))

    with patch.object(g._client, "get", side_effect=fake_get):
        g.geocode("Denver, CO", state_code="CO")

    assert captured["params"]["address"] == "Denver, CO"
    g.close()


def test_empty_address_returns_none_without_calling_api() -> None:
    g = GoogleGeocoder("test_key")
    with patch.object(g._client, "get") as mocked_get:
        r = g.geocode("", state_code="CO")
    assert r is None
    mocked_get.assert_not_called()
    g.close()


def test_returned_result_has_lat_lon_and_matched_address() -> None:
    g = GoogleGeocoder("test_key")
    payload = _payload(location_type="ROOFTOP", lat=12.34, lon=-56.78)
    with patch.object(g._client, "get", return_value=_mock_response(json_body=payload)):
        r = g.geocode("anywhere", state_code="CO")
    assert isinstance(r, GoogleResult)
    assert r.latitude == 12.34
    assert r.longitude == -56.78
    assert "Test, CO" in r.matched_address
    g.close()
