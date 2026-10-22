"""Frontier ordering: the tier ladder and the county cascade rule."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_DEFAULT_AGENCY_TYPES = ("bureau", "state_police", "dps", "ag")


@dataclass
class StateTarget:
    state: str
    agency_types: tuple[str, ...] = _DEFAULT_AGENCY_TYPES


@dataclass
class CountyTarget:
    state: str
    county: str
    population_rank: int


def state_frontier(covered: set[str], all_states: list[str]) -> list[StateTarget]:
    """One target per un-covered state, in the given order. Tier A."""
    return [StateTarget(s) for s in all_states if s not in covered]


def county_cascade(
    counties: list[CountyTarget],
    has_official: Callable[[CountyTarget], bool],
    floor: int = 10,
    dry_stop: int = 5,
) -> tuple[list[CountyTarget], list[CountyTarget]]:
    """Top-`floor` always scouted; past the floor, extend only while official
    sources keep turning up. Each hit grants up to `dry_stop` further lookahead;
    the cascade stops once `dry_stop` consecutive misses accumulate with no
    intervening hit. With no hits past the floor, only the floor is scouted.
    Returns (to_scout, deferred); nothing is dropped.

    `counties` must be pre-sorted by population (rank 1 = largest).
    """
    to_scout: list[CountyTarget] = []
    # Past the floor the streak starts "expired": extension is hit-driven, so a
    # miss with no preceding hit stops the cascade immediately.
    dry_streak = dry_stop
    stopped = False
    for i, county in enumerate(counties):
        if stopped:
            continue
        if i < floor:
            to_scout.append(county)
            continue
        if has_official(county):
            dry_streak = 0
            to_scout.append(county)
        elif dry_streak >= dry_stop:
            stopped = True
        else:
            dry_streak += 1
            to_scout.append(county)
    scouted_ids = {id(c) for c in to_scout}
    deferred = [c for c in counties if id(c) not in scouted_ids]
    return to_scout, deferred
