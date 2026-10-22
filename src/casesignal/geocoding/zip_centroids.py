"""Static ZIP code → centroid lat/lon lookup.

Backed by `data/static/zip_centroids.csv` (Census Bureau 2020 Gazetteer
ZCTA file, projected to three columns: zip_code, latitude, longitude).

Loaded once on first call and cached in a module-level dict (~5 MB
in-memory for the full national set). Worker startup pre-warms the
cache by calling `lookup()` against a known ZIP.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

_DEFAULT_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "static" / "zip_centroids.csv"


@lru_cache(maxsize=1)
def _load(data_path: str | None = None) -> dict[str, tuple[float, float]]:
    """Load ZIP centroids into a module-level dict.

    Cached via lru_cache so the file reads once per process. Tests can pass
    `data_path` to point at a fixture; production calls leave it None to
    use the bundled data.
    """
    path = Path(data_path) if data_path else _DEFAULT_DATA_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"ZIP centroid data file not found at {path}. "
            f"Refresh procedure documented in data/static/README.md."
        )
    out: dict[str, tuple[float, float]] = {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            zip_code = row["zip_code"].strip()
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (ValueError, KeyError):
                continue  # skip malformed rows; defensive only
            out[zip_code] = (lat, lon)
    return out


def lookup(zip_code: str, *, data_path: str | None = None) -> tuple[float, float] | None:
    """Return (latitude, longitude) for a ZIP code, or None if unknown.

    Accepts 5-digit ZIPs and ZIP+4 ('21206-1234'); the +4 portion is
    stripped before lookup.
    """
    if not zip_code:
        return None
    z = zip_code.strip().split("-", 1)[0]
    if len(z) != 5 or not z.isdigit():
        return None
    table = _load(data_path)
    return table.get(z)
