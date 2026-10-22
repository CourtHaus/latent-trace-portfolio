"""Geocoding service — orchestrates the Census + centroid fallback ladder.

Given a `GeocodingJobInput` (address text plus optional ZIP and county FIPS),
returns a `GeocodeResult` (lat/lon plus a precision tag).

Ladder:
1. Census Bureau street geocoder → precision = 'street'
2. ZIP centroid (if zip_code set) → precision = 'zip'
3. County centroid (if county_fips set) → precision = 'county'
4. Otherwise → precision = 'failed' (lat/lon = None)

The geocoding worker calls `geocode_for_job()` once per job and writes
the result back to `cold_case.cases`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Final, Literal

from casesignal.geocoding import county_centroids, zip_centroids
from casesignal.geocoding.census import CensusGeocoder
from casesignal.geocoding.google import GoogleGeocoder

logger = logging.getLogger(__name__)


GeocodePrecision = Literal["street", "landmark", "zip", "county", "failed"]


# Full state names + DC, used by the bare-state guard. We don't import a
# big static dataset for this; the set is tiny and stable. Keys are the
# two-letter codes we pass through state_code; values are the full names
# that show up in narrative-derived address text.
_US_STATE_NAMES: Final = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}


# State token must be followed by:
#   - a comma (e.g. ", CA, 90008")
#   - whitespace + 5-digit ZIP (e.g. ", OR 97322")
#   - end of string
# Without those anchors, "LA JARA, CO, 81140" matches "LA" before the
# actual state "CO" because "LA" is a valid two-letter code that prefixes
# the city name.
_STATE_IN_MATCHED_RE: Final = re.compile(r",\s*([A-Z]{2})\s*(?:,|\s+\d{5}|$)")


def _matched_state_differs(matched_address: str, target_state: str | None) -> bool:
    """True if Census's matched_address names a state other than `target_state`.

    Census returns addresses like ``"4201 DON TOMASO DR, LOS ANGELES, CA, 90008"``.
    When the regex extractor pulled an out-of-state address from a narrative
    (e.g., the suspect's former address in another state), the pin lands
    nowhere near the case's jurisdiction. Falling through to the next tier
    is the right call.

    Returns False when target_state is unknown (we can't compare) or when
    the matched_address has no recognizable two-letter state token.
    """
    if not target_state or not matched_address:
        return False
    m = _STATE_IN_MATCHED_RE.search(matched_address)
    if m is None:
        return False
    return m.group(1).upper() != target_state.upper()


def _is_bare_state(address: str | None, state_code: str | None) -> bool:
    """True if the address contains no locality info beyond a bare state.

    Calling Google with `"Utah"` returns APPROXIMATE → state centroid,
    which lands a `landmark` precision tag on a pin that's effectively
    in the middle of the state. That's strictly worse than the
    county-centroid fallback when we have `county_fips`, because the
    county pin at least reflects the right region.

    Detects two shapes:
      - `address` equals the bare state code (e.g., "UT", "MD")
      - `address` equals the full state name (e.g., "Utah", "Maryland")

    Anything else — `"Salt Lake City, UT"`, `"Utah, USA"`, `"UT, USA"`
    — has more structure than bare-state and is not flagged.
    """
    if not address:
        return False
    a = address.strip()
    if state_code and a.upper() == state_code.upper():
        return True
    # Any state's full name flagged, not just the one matching state_code:
    # the address might say "Utah" while state_code is None for older rows.
    return a in _US_STATE_NAMES.values()


@dataclass(frozen=True)
class GeocodingJobInput:
    address_text: str
    state_code: str | None = None
    zip_code: str | None = None
    county_fips: str | None = None


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float | None
    longitude: float | None
    precision: GeocodePrecision
    notes: str | None = None


class GeocodingService:
    """Orchestrates the geocoding ladder.

    Construct once per worker process with reusable HTTP clients (Census
    and Google) for connection reuse. The Google tier is env-gated:
    `GoogleGeocoder.from_env()` returns None when GOOGLE_MAPS_API_KEY is
    unset, and the ladder transparently skips it.

    Ladder order:
      1. Census  street geocoder         → 'street'    (free, broad U.S. coverage)
      2. Google  geocoder (if available) → 'street' or 'landmark'
      3. ZIP     centroid (static)       → 'zip'
      4. County  centroid (static)       → 'county'
      5. nothing                         → 'failed'
    """

    def __init__(
        self,
        *,
        census: CensusGeocoder | None = None,
        google: GoogleGeocoder | None = None,
    ) -> None:
        self._census = census or CensusGeocoder()
        self._owns_census = census is None
        # `google` may be None even after this assignment — that's how the
        # tier disables itself when no API key is provided.
        if google is not None:
            self._google: GoogleGeocoder | None = google
            self._owns_google = False
        else:
            self._google = GoogleGeocoder.from_env()
            self._owns_google = self._google is not None

    def close(self) -> None:
        if self._owns_census:
            self._census.close()
        if self._owns_google and self._google is not None:
            self._google.close()

    def geocode_for_job(self, job: GeocodingJobInput) -> GeocodeResult:
        """Run the full ladder for a single job; return the first hit."""

        # Tier 1: Census street geocoder.
        # Reject the hit if the matched address is in a different state than
        # job.state_code — the regex extractor sometimes pulls addresses from
        # narratives that mention out-of-state locations (e.g., where the
        # suspect previously lived). Without this guard those pins land far
        # from the case's actual jurisdiction.
        census_result = self._census.geocode(job.address_text, state_code=job.state_code)
        if census_result is not None and _matched_state_differs(
            census_result.matched_address, job.state_code
        ):
            census_result = None
        if census_result is not None:
            return GeocodeResult(
                latitude=census_result.latitude,
                longitude=census_result.longitude,
                precision="street",
                notes=(
                    f"census: {census_result.matched_address}"
                    if census_result.matched_address
                    else "census"
                ),
            )

        # Tier 2: Google geocoder (if API key configured).
        # Skip Google when the address is just a bare state — Google would
        # cheerfully return a state-centroid hit, which masquerades as
        # `landmark` precision but is geographically less useful than the
        # county-centroid we'd fall through to.
        if self._google is not None and not _is_bare_state(job.address_text, job.state_code):
            google_result = self._google.geocode(job.address_text, state_code=job.state_code)
            if google_result is not None:
                return GeocodeResult(
                    latitude=google_result.latitude,
                    longitude=google_result.longitude,
                    precision=google_result.tier,  # 'street' or 'landmark'
                    notes=(
                        f"google[{google_result.location_type}]: "
                        f"{google_result.matched_address}"
                    ),
                )

        # Tier 3: ZIP centroid
        if job.zip_code:
            zip_hit = zip_centroids.lookup(job.zip_code)
            if zip_hit is not None:
                lat, lon = zip_hit
                return GeocodeResult(
                    latitude=lat,
                    longitude=lon,
                    precision="zip",
                    notes=f"zip_centroid: {job.zip_code}",
                )

        # Tier 4: County centroid
        if job.county_fips:
            county_hit = county_centroids.lookup(job.county_fips)
            if county_hit is not None:
                return GeocodeResult(
                    latitude=county_hit.latitude,
                    longitude=county_hit.longitude,
                    precision="county",
                    notes=f"county_centroid: {county_hit.county_name}",
                )

        return GeocodeResult(
            latitude=None,
            longitude=None,
            precision="failed",
            notes="no tier produced a match",
        )
