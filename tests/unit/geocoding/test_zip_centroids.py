"""ZIP centroid lookup — known hits, unknowns, malformed inputs."""

from __future__ import annotations

from casesignal.geocoding import zip_centroids


def test_baltimore_county_zips_resolve() -> None:
    """Sample MD ZIPs known to be in BCounty cold-case narratives."""
    # 21206 — Baltimore (Casey Exampleton 2008)
    p = zip_centroids.lookup("21206")
    assert p is not None
    lat, lon = p
    assert 39.0 < lat < 40.0
    assert -77.0 < lon < -76.0

    # 21244 — Windsor Mill (Daley 1994)
    assert zip_centroids.lookup("21244") is not None

    # 21227 — Halethorpe (Cesnik 1970)
    assert zip_centroids.lookup("21227") is not None


def test_unknown_zip_returns_none() -> None:
    assert zip_centroids.lookup("99999") is None


def test_zip_plus_four_strips_extension() -> None:
    """ZIP+4 still resolves to the underlying ZIP centroid."""
    assert zip_centroids.lookup("21206-1234") is not None


def test_malformed_zip_returns_none() -> None:
    assert zip_centroids.lookup("") is None
    assert zip_centroids.lookup("abc12") is None
    assert zip_centroids.lookup("123") is None
    assert zip_centroids.lookup(None) is None  # type: ignore[arg-type]


def test_lookup_is_idempotent_across_calls() -> None:
    """Module-level cache returns the same dict object across calls."""
    p1 = zip_centroids.lookup("21206")
    p2 = zip_centroids.lookup("21206")
    assert p1 == p2
