"""Shared constants for MD-county cold-case adapters."""

from __future__ import annotations

MD_STATE: str = "MD"


# 5-digit FIPS code per county. Used by adapters to set
# cold_case.cases.source_county_fips, which the geocoding worker reads
# to fall back to county centroid when street + ZIP fail.
MD_COUNTY_FIPS: dict[str, str] = {
    "baltimore_county": "24005",
    "anne_arundel": "24003",
    "howard": "24027",
    "harford": "24025",
    "charles": "24017",
    "wicomico": "24045",
}


# User-visible county label for cold_case.cases.city. Distinct from the
# adapter package name (which is snake_case for filesystem).
MD_COUNTY_DISPLAY: dict[str, str] = {
    "baltimore_county": "Baltimore County",
    "anne_arundel": "Anne Arundel County",
    "howard": "Howard County",
    "harford": "Harford County",
    "charles": "Charles County",
    "wicomico": "Wicomico County",
}
