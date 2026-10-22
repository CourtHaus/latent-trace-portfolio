"""Corpus base rates -> surprisal weights for rarity-weighted correlation.

A match on a shared value v contributes -log2 P(v) bits, where P is the
Laplace-smoothed frequency of v among PUBLISHED cases where the dimension is
known. 'unknown' (and, for race, the canonical Unknown bucket) is missing,
not a value. Frequencies are cached in-process with a TTL so the engine
tracks corpus growth without a redeploy and without a migration.

Pure math (surprisal_weights, age_close_weight) is separated from the DB
fetch (_compute_base_rates) so tests never need the cache.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.correlation.config import (
    CORRELATION_AGE_CLOSE_YEARS,
    CORRELATION_BASE_RATES_TTL_SECONDS,
    CORRELATION_SMOOTHING_ALPHA,
)
from casesignal.normalization import RACE_UNKNOWN_CANONICAL, canonical_race


@dataclass(frozen=True)
class BaseRates:
    """Per-dimension surprisal weights (bits) + the age-closeness constant.

    Weight mappings are read-only views: the cached instance is shared across
    every caller in the process, so in-place mutation would corrupt scoring
    until the TTL expires. ``victim_race`` is keyed by CANONICAL bucket —
    scoring must canonicalize BOTH sides (normalization.canonical_race)
    before matching, or the probability model and the match disagree.
    """

    weapon: Mapping[str, float]
    location_type: Mapping[str, float]
    victim_gender: Mapping[str, float]
    victim_race: Mapping[str, float]
    age_close_weight: float


def surprisal_weights(
    counts: dict[str, int],
    alpha: float = CORRELATION_SMOOTHING_ALPHA,
) -> dict[str, float]:
    """-log2 of the Laplace-smoothed frequency for each value with count>0."""
    known = {v: c for v, c in counts.items() if c > 0}
    n = sum(known.values())
    k = len(known)
    if n == 0 or k == 0:
        return {}
    return {v: -math.log2((c + alpha) / (n + alpha * k)) for v, c in known.items()}


def age_close_weight(
    age_counts: dict[int, int],
    close_years: int = CORRELATION_AGE_CLOSE_YEARS,
) -> float:
    """Surprisal (bits) of two independent draws from the empirical age
    histogram landing within ``close_years`` of each other. This is the
    information value of an age match before the graded kernel scales it."""
    total = sum(age_counts.values())
    if total < 2:
        return 0.0
    close_pairs = 0
    items = sorted(age_counts.items())
    for a, ca in items:
        for b, cb in items:
            if abs(a - b) <= close_years:
                close_pairs += ca * cb
    p = close_pairs / (total * total)
    if p >= 1.0:
        return 0.0
    p = max(p, 1.0 / (total * total))
    return -math.log2(p)


_PUBLISHED_JOIN = """
      FROM cold_case.cases c
      JOIN etl.dataset_version dv
            ON dv.dataset_version_id = c.dataset_version_id
           AND dv.ingestion_status = 'published'
"""

_MO_COUNTS_SQL = text(f"""
    SELECT ext.weapon, ext.location_type
    {_PUBLISHED_JOIN}
      JOIN cold_case.case_extractions_current ext
            ON ext.case_id = c.case_id AND ext.prompt_tier = 1
""")

_VICTIM_COUNTS_SQL = text(f"""
    SELECT v.gender, v.race, v.age_num
    {_PUBLISHED_JOIN}
      JOIN LATERAL (
          SELECT gender, race, age_num
          FROM cold_case.victim
          WHERE case_id = c.case_id
          ORDER BY victim_id ASC
          LIMIT 1
      ) v ON true
""")


def _is_known(value: str | None) -> bool:
    return value is not None and value.strip().lower() != "unknown"


def _compute_base_rates(session: Session) -> BaseRates:
    weapon_counts: dict[str, int] = {}
    location_counts: dict[str, int] = {}
    for row in session.execute(_MO_COUNTS_SQL):
        if _is_known(row.weapon):
            weapon_counts[row.weapon] = weapon_counts.get(row.weapon, 0) + 1
        if _is_known(row.location_type):
            location_counts[row.location_type] = location_counts.get(row.location_type, 0) + 1

    gender_counts: dict[str, int] = {}
    race_counts: dict[str, int] = {}
    age_counts: dict[int, int] = {}
    for row in session.execute(_VICTIM_COUNTS_SQL):
        if _is_known(row.gender):
            gender_counts[row.gender] = gender_counts.get(row.gender, 0) + 1
        if row.race is not None:
            bucket = canonical_race(row.race)
            if bucket != RACE_UNKNOWN_CANONICAL:
                race_counts[bucket] = race_counts.get(bucket, 0) + 1
        if row.age_num is not None and 0 <= row.age_num <= 130:
            age_counts[int(row.age_num)] = age_counts.get(int(row.age_num), 0) + 1

    return BaseRates(
        weapon=MappingProxyType(surprisal_weights(weapon_counts)),
        location_type=MappingProxyType(surprisal_weights(location_counts)),
        victim_gender=MappingProxyType(surprisal_weights(gender_counts)),
        victim_race=MappingProxyType(surprisal_weights(race_counts)),
        age_close_weight=age_close_weight(age_counts),
    )


_cache: tuple[float, BaseRates] | None = None


def get_base_rates(session: Session) -> BaseRates:
    """TTL-cached corpus base rates (per process)."""
    global _cache
    cached = _cache  # snapshot: a concurrent clear can't null it mid-check
    now = time.monotonic()
    if cached is not None and (now - cached[0]) < CORRELATION_BASE_RATES_TTL_SECONDS:
        return cached[1]
    rates = _compute_base_rates(session)
    _cache = (now, rates)
    return rates


def clear_base_rates_cache() -> None:
    """Test hook (and manual ops escape hatch)."""
    global _cache
    _cache = None
