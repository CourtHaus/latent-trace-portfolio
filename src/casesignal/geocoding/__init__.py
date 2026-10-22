"""Geocoding package — Census Bureau API + ZIP/county centroid fallbacks.

Used by the async geocoding worker to resolve a postal address to a lat/lon
plus a precision tag. The worker writes the result back to
`cold_case.cases` and consumers (map, detail page) render based on the
precision tag.
"""

from casesignal.geocoding.service import (
    GeocodeResult,
    GeocodingJobInput,
    GeocodingService,
)

__all__ = ["GeocodeResult", "GeocodingJobInput", "GeocodingService"]
