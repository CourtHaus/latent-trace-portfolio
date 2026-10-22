"""Static county FIPS → centroid lat/lon lookup.

Backed by `data/static/county_centroids.csv` (Census Bureau 2020 Gazetteer
Counties file).

Index keys are full 5-digit FIPS (state + county). Lookup accepts either a
5-char county_fips OR a (state_code, county_fips) pair where county_fips
is just the 3-char county portion.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DEFAULT_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "static" / "county_centroids.csv"
)


@dataclass(frozen=True)
class CountyCentroid:
    state_code: str
    county_fips: str  # full 5-digit FIPS (state + county)
    state_fips: str
    county_name: str
    latitude: float
    longitude: float


@lru_cache(maxsize=1)
def _load(data_path: str | None = None) -> dict[str, CountyCentroid]:
    path = Path(data_path) if data_path else _DEFAULT_DATA_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"County centroid data file not found at {path}. "
            f"Refresh procedure documented in data/static/README.md."
        )
    out: dict[str, CountyCentroid] = {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (ValueError, KeyError):
                continue
            full_fips = row["county_fips"].strip()
            out[full_fips] = CountyCentroid(
                state_code=row["state_code"].strip(),
                county_fips=full_fips,
                state_fips=row["state_fips"].strip(),
                county_name=row["county_name"].strip(),
                latitude=lat,
                longitude=lon,
            )
    return out


def lookup(county_fips: str, *, data_path: str | None = None) -> CountyCentroid | None:
    """Return a CountyCentroid by 5-digit FIPS code, or None if unknown."""
    if not county_fips:
        return None
    fips = county_fips.strip()
    if len(fips) != 5 or not fips.isdigit():
        return None
    table = _load(data_path)
    return table.get(fips)
