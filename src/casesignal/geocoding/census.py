"""Census Bureau onelineaddress geocoder client.

Calls https://geocoding.geo.census.gov/geocoder/locations/onelineaddress
with a postal address and returns the best match's lat/lon.

The Census Bureau's free geocoder is the primary tier of our fallback
ladder for street-level precision. No API key, no per-key rate limit,
generous coverage of "block of <Street>" patterns common in U.S.
police narratives.

This client is intentionally NOT polite_http — Census is a public API
that doesn't need rate-limiting or robots.txt enforcement; we just
need a small retry on transient failures. It's also not used by the
HTML scraper.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
_DEFAULT_BENCHMARK = "Public_AR_Current"
_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_MAX_RETRIES = 2


@dataclass(frozen=True)
class CensusResult:
    latitude: float
    longitude: float
    matched_address: str


class CensusGeocoder:
    """Thin wrapper over the Census onelineaddress endpoint.

    Construct once per worker process; reuse across many geocoding jobs.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        benchmark: str = _DEFAULT_BENCHMARK,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.benchmark = benchmark
        self._client = httpx.Client(timeout=self.timeout_seconds)

    def __enter__(self) -> CensusGeocoder:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def geocode(self, address: str, *, state_code: str | None = None) -> CensusResult | None:
        """Geocode a single address. Returns None if no match.

        We append the state to the address when provided so Census's
        matcher knows the country/region context (its onelineaddress
        endpoint doesn't take a separate state field).
        """
        if not address or not address.strip():
            return None

        full_address = address.strip()
        if state_code and state_code.upper() not in full_address.upper():
            full_address = f"{full_address}, {state_code}"

        params = {
            "address": full_address,
            "benchmark": self.benchmark,
            "format": "json",
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.get(_CENSUS_URL, params=params)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                logger.info(
                    "census geocoder transient error (attempt %d/%d): %r",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    continue
                return None

            if response.status_code >= 500 and attempt < self.max_retries:
                continue

            if response.status_code != 200:
                logger.warning(
                    "census geocoder returned HTTP %d for %r",
                    response.status_code,
                    full_address,
                )
                return None

            try:
                payload = response.json()
            except ValueError:
                logger.warning("census geocoder returned non-JSON for %r", full_address)
                return None

            return _parse_match(payload)

        return None


def _parse_match(payload: dict[str, Any]) -> CensusResult | None:
    """Extract the first match from a Census geocoder JSON response."""
    matches = payload.get("result", {}).get("addressMatches") or []
    if not matches:
        return None
    first = matches[0]
    coords = first.get("coordinates") or {}
    try:
        lon = float(coords["x"])
        lat = float(coords["y"])
    except (KeyError, ValueError, TypeError):
        return None
    return CensusResult(
        latitude=lat,
        longitude=lon,
        matched_address=str(first.get("matchedAddress", "")),
    )
