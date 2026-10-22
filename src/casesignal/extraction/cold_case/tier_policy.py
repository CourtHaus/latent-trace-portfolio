"""Policy for which cold-case extraction tiers should run by source state.

Tier-2 extracts incident_date, address, victim_age, victim_gender (race was
removed in V3 — see feedback-no-llm-race-inference). When a state's source
adapter already provides ALL four fields with provenance ``source``, Tier-2
is fully redundant. For states with only partial source coverage, Tier-2
fills the gaps and is worth running.

The cost calculus changed when the project moved to local Qwen3:14b (see
feedback-local-only-llm-extraction). API spend is no longer a tiebreaker —
the only question is whether Tier-2's output adds information the source
doesn't already provide.

Per-state rationale below. To add a state: confirm in its adapter's
``transform.py`` that gender + age + (date | address from source) are
present, then add it here. To remove a state: confirm the adapter has
at least one Tier-2 field NOT coming from the source feed.
"""

from __future__ import annotations

# State 2-letter codes. The mapping is the authoritative source for which
# cold-case states have full source-provided Tier-2 fields. Per-state notes
# capture WHICH fields are source-provided so the decision is auditable.
_DISABLED: dict[str, str] = {
    # Full demographics + structured date/address from CBI CSV columns.
    "CO": "gender, age, date, address all from source (CBI CSV)",
    # Full demographics from MN BCA SharePoint list (gender, age).
    # The MN adapter actively enqueues Tier-2 jobs that should be skipped.
    "MN": "gender, age all from source (BCA SharePoint list)",
    # Full demographics from BCI structured fields.
    "UT": "gender, age all from source (UT BCI)",
    # Full demographics from WY DCI Looker Studio export (CSV columns).
    "WY": "gender, age all from source (WY DCI export)",
}

# Previously also included FL, OH, DC. Re-enabled 2026-05-26 when the project
# moved to local Qwen3:14b: those states' source feeds publish only gender
# (DC) or gender+race (FL, OH), leaving age + address + date as fields Tier-2
# can fill. With $0 marginal extraction cost there's no reason to skip them.

TIER2_DISABLED_STATES = frozenset(_DISABLED)


def tier2_enabled_for_state(state: str | None) -> bool:
    if state is None:
        return True
    return state.strip().upper() not in TIER2_DISABLED_STATES
