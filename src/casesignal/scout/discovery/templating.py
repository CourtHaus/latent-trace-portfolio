"""Pure web-search query templating for the two frontier tiers."""

from __future__ import annotations

from casesignal.scout.frontier import CountyTarget, StateTarget

_STATE_NAMES = {"TX": "Texas", "NM": "New Mexico", "OK": "Oklahoma", "AR": "Arkansas"}
# Full 50-state map is filled in Task 10 wiring; templating stays name-driven.

_AGENCY_PHRASES = {
    "bureau": "bureau of investigation",
    "state_police": "state police",
    "dps": "department of public safety",
    "ag": "attorney general cold case unit",
}


def _state_name(code: str) -> str:
    return _STATE_NAMES.get(code, code)


def queries_for_state(t: StateTarget) -> list[str]:
    name = _state_name(t.state)
    return [f"{name} {_AGENCY_PHRASES[a]} cold case unsolved homicide" for a in t.agency_types]


def queries_for_county(t: CountyTarget) -> list[str]:
    name = _state_name(t.state)
    return [
        f"{t.county} County {name} sheriff cold case unsolved homicide",
        f"{t.county} County {name} police department cold case",
    ]
