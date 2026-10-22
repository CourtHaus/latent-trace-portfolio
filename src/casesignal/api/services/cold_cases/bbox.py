"""Bounding-box parsing + map endpoint row limits."""

from __future__ import annotations

DEFAULT_MAP_LIMIT = 5000
MAX_MAP_LIMIT = 10000

# Leaflet zoom at/above which the map returns individual case points; below
# it, the map returns server-aggregated grid clusters. At zoom 8 a viewport
# is roughly metro-scale — small enough that per-viewport point counts ship
# and render without the browser holding the whole corpus.
CLUSTER_ZOOM_THRESHOLD = 8


def cluster_cell_degrees(zoom: int) -> float:
    """Grid cell size in decimal degrees for server-side map clustering.

    Sized so a cell is ~70 screen pixels at the given Leaflet zoom level:
    a web-mercator tile is 256 px for 360°, so degrees-per-pixel is
    360 / (256 * 2**zoom) and a 70 px cell is ~98 / 2**zoom. Clamped to keep
    cells sane at extreme zooms.
    """
    raw = 98.0 / (2.0 ** max(zoom, 0))
    return min(max(raw, 0.05), 45.0)


def parse_bbox(raw: str) -> tuple[float, float, float, float]:
    """Parse a 'west,south,east,north' bbox string.

    Raises ValueError with a descriptive message on any shape / range / degeneracy
    violation. The 422 wrapping happens at the route layer.
    """
    parts = raw.split(",")
    if len(parts) != 4:
        raise ValueError("bbox must have exactly 4 comma-separated values (west,south,east,north)")

    try:
        west, south, east, north = (float(p.strip()) for p in parts)
    except ValueError as exc:
        raise ValueError("bbox values must be numeric") from exc

    if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
        raise ValueError("bbox longitude out of range [-180, 180]")
    if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
        raise ValueError("bbox latitude out of range [-90, 90]")
    if east <= west or north <= south:
        raise ValueError("bbox is degenerate (east must be > west, north must be > south)")

    return (west, south, east, north)
