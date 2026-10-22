"""Split a single Utah BCI 'Race' source value into (race, ethnicity).

Utah conflates race and ethnicity in the source — e.g., the Race field on
a Hispanic victim is published as "Hispanic" (which is technically an
ethnicity, not a race). Three-element allowlist routes those terms to the
canonical `cold_case.victim.ethnicity` column; everything else flows to
`cold_case.victim.race`.

This is a hardcoded allowlist (3 terms), not an inference. The rule preserves
source fidelity while populating the schema's intended columns.
"""

from __future__ import annotations

_ETHNICITY_TERMS = frozenset({"hispanic", "latino", "latina"})


def classify(source_value: str | None) -> tuple[str | None, str | None]:
    """Return a (race, ethnicity) tuple from a single source Race-field value.

    The returned strings preserve original capitalization (stripped of leading
    and trailing whitespace). Empty / None input yields (None, None).
    """
    if not source_value:
        return None, None
    stripped = source_value.strip()
    if not stripped:
        return None, None
    if stripped.lower() in _ETHNICITY_TERMS:
        return None, stripped
    return stripped, None
