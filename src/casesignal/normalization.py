"""Source-value normalization shared across layers.

Race canonicalization (NIBRS buckets) moved here from the API filters module
(PR #204 origin) so the correlation engine can canonicalize before matching
without importing the api package (api already imports correlation).
Deterministic synonym mapping only — never inference
(see feedback-no-llm-race-inference).

Distinct from ``etl/services/normalizers.py`` (ingest-time FORMAT normalizers:
casing, dates, gender codes); this module holds cross-layer canonical MAPS.
"""

from __future__ import annotations

# Victim-race canonicalization. Source agencies record race in ~24 different
# spellings/casings for the same handful of concepts ("Black", "BLACK or AFRICAN
# AMERICAN", "African American"; "White", "Caucasian", "White/Caucasian"; ...).
# Left raw, the filter facet fragments and selecting one spelling silently misses
# rows tagged with another. This is a DETERMINISTIC synonym map over
# SOURCE-PROVIDED values — not inference (no model, no prediction); the raw value
# is preserved on the victim row and shown verbatim on the detail page. Buckets
# follow the FBI UCR/NIBRS race categories. Hispanic/Latino is an ethnicity, not
# a NIBRS race, but sources store it in the race field, so it is carried as a
# pragmatic bucket (see the methodology note). "Asian or Pacific Islander" is the
# older combined OMB category and folds to Asian; standalone Pacific Islander /
# Polynesian fold to the NH/OPI bucket. Keys are LOWERCASED source values because
# the SQL match is on LOWER(v.race).
_BLACK = "Black or African American"
_WHITE = "White"
_HISPANIC = "Hispanic or Latino"
_ASIAN = "Asian"
_AIAN = "American Indian or Alaska Native"
_NHOPI = "Native Hawaiian or Other Pacific Islander"
_OTHER = "Other"
_UNKNOWN = "Unknown"

RACE_CANONICAL_MAP: dict[str, str] = {
    "black": _BLACK,
    "black or african american": _BLACK,
    "african american": _BLACK,
    "white": _WHITE,
    "caucasian": _WHITE,
    "white/caucasian": _WHITE,
    "white/ caucasian": _WHITE,
    "hispanic": _HISPANIC,
    "hispanic or latino": _HISPANIC,
    "hispanic/latino": _HISPANIC,
    "asian": _ASIAN,
    "asian or pacific islander": _ASIAN,
    "american indian": _AIAN,
    "american indian or alaskan native": _AIAN,
    "american indian or alaska native": _AIAN,
    "native american": _AIAN,
    "pacific islander": _NHOPI,
    "polynesian": _NHOPI,
    "biracial": _OTHER,
    "brown": _OTHER,
    "middle eastern": _OTHER,
    "caucasian\\hispanic or latino": _OTHER,
    "unknown": _UNKNOWN,
}

# Any source spelling not in the map (a new/unanticipated value) folds here, so
# the facet never silently drops a value. A unit test asserts the known source
# vocabulary is fully mapped, so this only catches genuinely new spellings.
RACE_FALLBACK_CANONICAL = _OTHER

# Reverse: canonical bucket -> all lowercased source forms that fold into it.
# Used to expand a selected bucket back to every raw spelling for the SQL match.
RACE_CANONICAL_TO_SOURCES: dict[str, list[str]] = {}
for _src, _canon in RACE_CANONICAL_MAP.items():
    RACE_CANONICAL_TO_SOURCES.setdefault(_canon, []).append(_src)

# Every lowercased source spelling that folds to a SPECIFIC (non-Other) bucket.
# "Other" is matched as the COMPLEMENT of these (see race_exclude_filter), not as
# a fixed positive list, so it captures the explicit Other spellings AND any
# future UNMAPPED spelling — exactly what canonical_race folds to Other in the
# facet/counts. This keeps the filter and the facet in agreement under data
# drift: without it, a new spelling would show in the Other count but be missed
# by the Other filter (Codex P2).
RACE_NON_OTHER_SOURCES: list[str] = sorted(
    src for src, canon in RACE_CANONICAL_MAP.items() if canon != _OTHER
)


def canonical_race(raw: str) -> str:
    """Map a raw source race value to its canonical NIBRS bucket."""
    return RACE_CANONICAL_MAP.get(raw.strip().lower(), RACE_FALLBACK_CANONICAL)


# The canonical bucket that means "source said unknown" — treated as MISSING
# by consumers that score or facet on race.
RACE_UNKNOWN_CANONICAL = _UNKNOWN
