"""Utah county-name → 5-digit FIPS lookup + city fallback.

UT has 29 counties. FIPS codes use prefix "49" + a 3-digit county code.
Source: Census Bureau 2024 county FIPS codes
(https://www.census.gov/library/reference/code-lists/ansi.html).

Utah detail pages sometimes publish County, sometimes only City. The fallback
table covers the ~20 largest Utah cities to recover the county when only City
is available. Cases where neither matches yield None (transform.py logs and
writes source_county_fips=NULL; geocoding may recover downstream).
"""

from __future__ import annotations

COUNTY_FIPS: dict[str, str] = {
    "Beaver": "49001",
    "Box Elder": "49003",
    "Cache": "49005",
    "Carbon": "49007",
    "Daggett": "49009",
    "Davis": "49011",
    "Duchesne": "49013",
    "Emery": "49015",
    "Garfield": "49017",
    "Grand": "49019",
    "Iron": "49021",
    "Juab": "49023",
    "Kane": "49025",
    "Millard": "49027",
    "Morgan": "49029",
    "Piute": "49031",
    "Rich": "49033",
    "Salt Lake": "49035",
    "San Juan": "49037",
    "Sanpete": "49039",
    "Sevier": "49041",
    "Summit": "49043",
    "Tooele": "49045",
    "Uintah": "49047",
    "Utah": "49049",
    "Wasatch": "49051",
    "Washington": "49053",
    "Wayne": "49055",
    "Weber": "49057",
}

_LOWER: dict[str, str] = {k.lower(): v for k, v in COUNTY_FIPS.items()}


# City → county canonical-name lookup for the ~40 largest UT cities.
_CITY_TO_COUNTY: dict[str, str] = {
    "salt lake city": "Salt Lake",
    "south salt lake": "Salt Lake",
    "west valley city": "Salt Lake",
    "west valley": "Salt Lake",  # alias — parser may strip "City" from colloquial agency names
    "west jordan": "Salt Lake",
    "sandy": "Salt Lake",
    "south jordan": "Salt Lake",
    "millcreek": "Salt Lake",
    "taylorsville": "Salt Lake",
    "draper": "Salt Lake",
    "murray": "Salt Lake",
    "midvale": "Salt Lake",
    "cottonwood heights": "Salt Lake",
    "kearns": "Salt Lake",
    "magna": "Salt Lake",
    "provo": "Utah",
    "orem": "Utah",
    "lehi": "Utah",
    "american fork": "Utah",
    "spanish fork": "Utah",
    "pleasant grove": "Utah",
    "saratoga springs": "Utah",
    "ogden": "Weber",
    "roy": "Weber",
    "south ogden": "Weber",
    "north ogden": "Weber",
    "layton": "Davis",
    "bountiful": "Davis",
    "clearfield": "Davis",
    "kaysville": "Davis",
    "syracuse": "Davis",
    "logan": "Cache",
    "st. george": "Washington",
    "saint george": "Washington",
    "washington": "Washington",
    "hurricane": "Washington",
    "cedar city": "Iron",
    "park city": "Summit",
    "tooele": "Tooele",
    "vernal": "Uintah",
    "price": "Carbon",
    "moab": "Grand",
    "richfield": "Sevier",
    "heber city": "Wasatch",
    "brigham city": "Box Elder",
    "helper": "Carbon",  # small Carbon County city; Phase 4.2 geocode recovery
    "sunset": "Davis",  # small Davis County city; Phase 4.2 geocode recovery
    "roosevelt": "Duchesne",  # Duchesne County seat; Phase 4.2 geocode recovery
}


def lookup(county_name: str | None) -> str | None:
    """Return 5-digit FIPS for a UT county; None if not found.

    Strips trailing " County" / " county" and matches case-insensitively.
    """
    if not county_name:
        return None
    cleaned = county_name.strip().rstrip(".").lower()
    if cleaned.endswith(" county"):
        cleaned = cleaned[: -len(" county")].strip()
    return _LOWER.get(cleaned)


def lookup_with_city_fallback(
    *,
    city: str | None,
    county: str | None,
) -> str | None:
    """Try county first; if absent or unmatched, try city-to-county fallback."""
    if county:
        fips = lookup(county)
        if fips is not None:
            return fips
    if city:
        canonical = _CITY_TO_COUNTY.get(city.strip().lower())
        if canonical:
            return _LOWER[canonical.lower()]
    return None
