"""GeocodingService — orchestrates the Census → Google → ZIP → county fallback ladder."""

from __future__ import annotations

from unittest.mock import MagicMock

from pytest import MonkeyPatch

from casesignal.geocoding.census import CensusResult
from casesignal.geocoding.google import GoogleResult
from casesignal.geocoding.service import (
    GeocodingJobInput,
    GeocodingService,
)


def _make_service(
    census_result: CensusResult | None = None,
    google_result: GoogleResult | None = None,
    *,
    enable_google: bool = False,
) -> GeocodingService:
    """Build a GeocodingService with mocked Census and (optionally) Google.

    Google is disabled by default — most legacy tests don't expect that tier
    to fire. Pass `enable_google=True` to inject a mock Google client.
    """
    fake_census = MagicMock()
    fake_census.geocode.return_value = census_result

    if enable_google:
        fake_google = MagicMock()
        fake_google.geocode.return_value = google_result
        return GeocodingService(census=fake_census, google=fake_google)

    # Sentinel that GeocodingService treats as "Google tier off". The
    # constructor only auto-creates from env when `google=None`, so we wrap
    # a MagicMock returning None and inject it to suppress env-based init.
    fake_google = MagicMock()
    fake_google.geocode.return_value = None
    return GeocodingService(census=fake_census, google=fake_google)


def test_census_hit_yields_street_precision() -> None:
    fake = CensusResult(
        latitude=39.3384,
        longitude=-76.5388,
        matched_address="6000 BARSTOW RD, BALTIMORE, MD, 21206",
    )
    service = _make_service(census_result=fake)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="6000 block of Barstow Rd",
            state_code="MD",
            zip_code="21206",
            county_fips="24005",
        )
    )

    assert result.precision == "street"
    assert result.latitude == 39.3384
    assert result.longitude == -76.5388


def test_falls_back_to_zip_when_census_misses() -> None:
    service = _make_service(census_result=None)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="some unrecognized address",
            state_code="MD",
            zip_code="21206",
            county_fips="24005",
        )
    )

    assert result.precision == "zip"
    assert result.latitude is not None
    assert result.longitude is not None
    # 21206 centroid is roughly Baltimore-area
    assert 39.0 < result.latitude < 40.0


def test_falls_back_to_county_when_zip_unknown() -> None:
    service = _make_service(census_result=None)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="address with no good ZIP",
            state_code="MD",
            zip_code="99999",  # unknown
            county_fips="24005",
        )
    )

    assert result.precision == "county"
    assert result.latitude is not None
    # Baltimore County centroid lat range
    assert 39.0 < result.latitude < 40.0


def test_falls_back_to_county_when_zip_missing() -> None:
    service = _make_service(census_result=None)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="address with no ZIP at all",
            state_code="MD",
            zip_code=None,
            county_fips="24005",
        )
    )

    assert result.precision == "county"


def test_failed_when_no_tier_produces_a_hit() -> None:
    service = _make_service(census_result=None)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="totally unknowable",
            state_code="ZZ",
            zip_code=None,
            county_fips=None,
        )
    )

    assert result.precision == "failed"
    assert result.latitude is None
    assert result.longitude is None


def test_google_landmark_hit_fires_when_census_misses() -> None:
    google_hit = GoogleResult(
        latitude=39.7392,
        longitude=-104.9903,
        matched_address="Denver, CO, USA",
        tier="landmark",
        location_type="APPROXIMATE",
    )
    service = _make_service(census_result=None, google_result=google_hit, enable_google=True)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="Denver, CO",
            state_code="CO",
            zip_code="80202",  # would otherwise fall to ZIP centroid
            county_fips="08031",
        )
    )

    assert result.precision == "landmark"
    assert result.latitude == 39.7392
    assert result.longitude == -104.9903
    assert "google[APPROXIMATE]" in (result.notes or "")


def test_google_rooftop_hit_yields_street_precision() -> None:
    google_hit = GoogleResult(
        latitude=39.7439,
        longitude=-104.9879,
        matched_address="321 17th St, Denver, CO 80202, USA",
        tier="street",
        location_type="ROOFTOP",
    )
    service = _make_service(census_result=None, google_result=google_hit, enable_google=True)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="Brown Palace Hotel, Denver, CO",
            state_code="CO",
        )
    )

    assert result.precision == "street"
    assert "google[ROOFTOP]" in (result.notes or "")


def test_google_tier_disabled_when_no_api_key(monkeypatch: MonkeyPatch) -> None:
    """Without google injected and no env var, the Google tier silently skips."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    fake_census = MagicMock()
    fake_census.geocode.return_value = None
    service = GeocodingService(census=fake_census)  # google omitted

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="Denver, CO",
            state_code="CO",
            zip_code=None,
            county_fips="08031",
        )
    )

    # No Google → falls all the way to county centroid
    assert result.precision == "county"


def test_bare_state_skips_google_and_falls_to_county() -> None:
    """When address is just 'Utah', Google would return a state-centroid
    hit tagged `landmark` — geographically less useful than the county
    centroid we have via county_fips. Guard skips Google entirely."""
    google_hit = GoogleResult(
        latitude=39.32,
        longitude=-111.09,
        matched_address="Utah, USA",
        tier="landmark",
        location_type="APPROXIMATE",
    )
    service = _make_service(census_result=None, google_result=google_hit, enable_google=True)
    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="Utah",
            state_code="UT",
            zip_code=None,
            county_fips="49035",
        )
    )
    assert result.precision == "county"
    assert "county_centroid" in (result.notes or "")


def test_bare_state_code_also_skips_google() -> None:
    google_hit = GoogleResult(
        latitude=39.32,
        longitude=-111.09,
        matched_address="UT, USA",
        tier="landmark",
        location_type="APPROXIMATE",
    )
    service = _make_service(census_result=None, google_result=google_hit, enable_google=True)
    result = service.geocode_for_job(
        GeocodingJobInput(address_text="UT", state_code="UT", county_fips="49035")
    )
    assert result.precision == "county"


def test_city_state_still_calls_google() -> None:
    """Guard must NOT fire when address has city info — 'Salt Lake City, UT'
    is exactly the case Google handles well."""
    google_hit = GoogleResult(
        latitude=40.76,
        longitude=-111.89,
        matched_address="Salt Lake City, UT, USA",
        tier="landmark",
        location_type="APPROXIMATE",
    )
    service = _make_service(census_result=None, google_result=google_hit, enable_google=True)
    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="Salt Lake City, UT",
            state_code="UT",
            county_fips="49035",
        )
    )
    assert result.precision == "landmark"
    assert "Salt Lake City" in (result.notes or "")


def test_census_match_in_wrong_state_is_rejected() -> None:
    """Census happily geocodes 'Los Angeles, CA' even when state_code='CO'.
    Without the state-mismatch guard, the case lands ~1000 miles from
    its actual jurisdiction. With the guard, we fall through to the next
    tier (Google → ZIP → county centroid)."""
    out_of_state_hit = CensusResult(
        latitude=34.0048,
        longitude=-118.3464,
        matched_address="4201 DON TOMASO DR, LOS ANGELES, CA, 90008",
    )
    service = _make_service(census_result=out_of_state_hit)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="4201 Don Tomaso Drive, Los Angeles, CA",
            state_code="CO",
            zip_code=None,
            county_fips="08005",  # Aurora's county
        )
    )

    # Census hit rejected → falls to county centroid
    assert result.precision == "county"


def test_census_match_in_correct_state_is_accepted() -> None:
    """The state-mismatch guard must NOT reject correct matches —
    'LA JARA, CO' has 'LA' as a city prefix; the regex must find 'CO'
    as the state."""
    in_state_hit = CensusResult(
        latitude=37.27,
        longitude=-105.96,
        matched_address="500 MAIN ST, LA JARA, CO, 81140",
    )
    service = _make_service(census_result=in_state_hit)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="500 S. Main Street, La Jara, CO",
            state_code="CO",
            zip_code=None,
            county_fips="08023",
        )
    )

    assert result.precision == "street"


def test_failed_when_tier_inputs_invalid() -> None:
    service = _make_service(census_result=None)

    result = service.geocode_for_job(
        GeocodingJobInput(
            address_text="address",
            state_code="MD",
            zip_code="not-a-zip",
            county_fips="not-a-fips",
        )
    )

    assert result.precision == "failed"
