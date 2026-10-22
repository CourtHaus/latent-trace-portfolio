"""Value score with confidence damping. Hard gates gate scoring entirely."""

from __future__ import annotations

import math

from casesignal.scout.models import Candidate, Confidence, GateResult, Location

_DAMPING: dict[Confidence | None, float] = {
    Confidence.EXACT: 1.0,
    Confidence.PROBED: 0.8,
    Confidence.VISIBLE: 0.5,
}
_CORE_FIELDS = ("victim_name", "incident_date", "county", "city", "race", "sex")


def score_candidate(c: Candidate) -> tuple[float | None, dict[str, float]]:
    gates = c.gates
    if (
        gates is None
        or gates.cold_homicide != GateResult.PASS
        or gates.official_first_party != GateResult.PASS
    ):
        return None, {}

    count = c.case_count.value if c.case_count else None
    count_norm = 0.3 if count is None else min(1.0, math.log10(max(count, 1)) / 3)

    conf = c.case_count.confidence if c.case_count else None
    damping = _DAMPING.get(conf, 0.5)

    plottability = c.plottability if c.plottability is not None else 0.5

    structured = sum(
        1
        for n in _CORE_FIELDS
        if (f := c.fields.get(n)) and f.present and f.location == Location.STRUCTURED
    )
    structure_bonus = 1.0 + 0.25 * (structured / len(_CORE_FIELDS))

    score = count_norm * damping * plottability * structure_bonus
    breakdown = {
        "count": round(count_norm, 4),
        "damping": round(damping, 4),
        "plottability": round(plottability, 4),
        "structure": round(structure_bonus, 4),
    }
    return round(score, 4), breakdown
