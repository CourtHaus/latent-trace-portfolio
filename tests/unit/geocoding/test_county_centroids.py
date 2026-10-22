"""County centroid lookup — Baltimore County FIPS 24005 + edge cases."""

from __future__ import annotations

from casesignal.geocoding import county_centroids


def test_baltimore_county_md_resolves() -> None:
    centroid = county_centroids.lookup("24005")
    assert centroid is not None
    assert centroid.state_code == "MD"
    assert centroid.county_name == "Baltimore County"
    assert centroid.state_fips == "24"
    assert centroid.county_fips == "24005"
    # Baltimore County centroid is roughly NE of Baltimore City
    assert 39.0 < centroid.latitude < 40.0
    assert -77.0 < centroid.longitude < -76.0


def test_unknown_fips_returns_none() -> None:
    assert county_centroids.lookup("99999") is None


def test_malformed_fips_returns_none() -> None:
    assert county_centroids.lookup("") is None
    assert county_centroids.lookup("abc") is None
    assert county_centroids.lookup("24") is None  # too short


def test_lookup_returns_county_centroid_with_full_fields() -> None:
    centroid = county_centroids.lookup("24005")
    assert centroid is not None
    # Fields exposed for use by GeocodingService notes + future API surface
    assert hasattr(centroid, "state_code")
    assert hasattr(centroid, "county_fips")
    assert hasattr(centroid, "state_fips")
    assert hasattr(centroid, "county_name")
    assert hasattr(centroid, "latitude")
    assert hasattr(centroid, "longitude")
