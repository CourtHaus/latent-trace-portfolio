"""Google Maps Geocoding API client — landmark-aware tier of the ladder.

Calls https://maps.googleapis.com/maps/api/geocode/json with a free-text
address and returns the best match's lat/lon plus a classified precision
tier based on Google's `location_type`:

  ROOFTOP            → "street"   (full address, geocoded to building)
  RANGE_INTERPOLATED → "street"   (interpolated along a known segment)
  GEOMETRIC_CENTER   → "landmark" (roads, businesses, neighborhoods)
  APPROXIMATE        → "landmark" (cities, regions, vague matches)

This tier sits between Census and ZIP/county centroids: Census handles
clean street addresses for free; Google handles roads, named landmarks,
businesses, and city-level fallback (still better than county centroid).

Env-gated: if GOOGLE_MAPS_API_KEY is unset, the factory returns None
and the service-level ladder skips this tier. Never log the key.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_MAX_RETRIES = 2

GoogleTier = Literal["street", "landmark"]


@dataclass(frozen=True)
class GoogleResult:
    latitude: float
    longitude: float
    matched_address: str
    tier: GoogleTier
    location_type: str  # raw Google value, surfaced into notes


class GoogleGeocoder:
    """Thin wrapper over Google's Geocoding API.

    Construct once per worker process via `from_env()`; reuse across jobs.
    """

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        region_bias: str = "us",
    ) -> None:
        if not api_key:
            raise ValueError("GoogleGeocoder requires a non-empty api_key")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.region_bias = region_bias
        self._client = httpx.Client(timeout=self.timeout_seconds)

    @classmethod
    def from_env(cls) -> GoogleGeocoder | None:
        """Construct from GOOGLE_MAPS_API_KEY env var. Returns None if unset."""
        key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
        if not key:
            return None
        return cls(key)

    def __enter__(self) -> GoogleGeocoder:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def geocode(self, address: str, *, state_code: str | None = None) -> GoogleResult | None:
        if not address or not address.strip():
            return None

        full_address = address.strip()
        if state_code and state_code.upper() not in full_address.upper():
            full_address = f"{full_address}, {state_code}"

        params: dict[str, str] = {
            "address": full_address,
            "key": self._api_key,
            "region": self.region_bias,
        }
        # `components` is a hard filter on Google's side — when set, the
        # geocoder cannot return a result outside the named administrative
        # area / country. Without this, Google's free-text matcher will
        # happily map "34th Avenue and Marion Street, Denver, CO" to a
        # 34th Ave SE in Oregon when it doesn't find a perfect Denver
        # match (verified in production data 2026-05-12).
        if state_code:
            params["components"] = f"country:US|administrative_area:{state_code.upper()}"
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.get(GOOGLE_URL, params=params)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                logger.info(
                    "google geocoder transient error (attempt %d/%d): %r",
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
                    "google geocoder returned HTTP %d for address (status code only — body not logged to keep key out of logs)",
                    response.status_code,
                )
                return None

            try:
                payload = response.json()
            except ValueError:
                logger.warning("google geocoder returned non-JSON")
                return None

            status = payload.get("status", "")
            if status == "ZERO_RESULTS":
                return None
            if status == "OVER_QUERY_LIMIT":
                logger.warning("google geocoder OVER_QUERY_LIMIT — billing or quota issue")
                return None
            if status == "REQUEST_DENIED":
                # API-key problem; log without leaking the key value.
                logger.warning("google geocoder REQUEST_DENIED — check API key restrictions")
                return None
            if status != "OK":
                logger.warning("google geocoder unexpected status: %s", status)
                return None

            return _parse_first_match(payload)

        return None


def _parse_first_match(payload: dict[str, Any]) -> GoogleResult | None:
    results = payload.get("results") or []
    if not results:
        return None
    first = results[0]
    geometry = first.get("geometry") or {}
    location = geometry.get("location") or {}
    location_type = str(geometry.get("location_type", ""))
    try:
        lat = float(location["lat"])
        lon = float(location["lng"])
    except (KeyError, ValueError, TypeError):
        return None

    if location_type in ("ROOFTOP", "RANGE_INTERPOLATED"):
        tier: GoogleTier = "street"
    else:
        tier = "landmark"

    return GoogleResult(
        latitude=lat,
        longitude=lon,
        matched_address=str(first.get("formatted_address", "")),
        tier=tier,
        location_type=location_type,
    )
