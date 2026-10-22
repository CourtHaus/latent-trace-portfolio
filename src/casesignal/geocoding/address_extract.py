"""Regex-based address extraction from free-text police narratives.

Many cold-case sources publish a narrative paragraph per case but no
structured `address` field. The Census + Google geocoders both need an
address-shaped string to work with — sending raw narrative prose to
either tier returns ZERO_RESULTS for almost everything.

This module provides `extract_address`, which scans a narrative for the
seven address shapes that show up in U.S. police writing (block-of,
standard street address, intersections, "between X and Y", lone street
near a landmark) and returns the best match as a normalized fragment,
optionally suffixed with city / state for geocoder anchoring.

The patterns originated in the Colorado adapter and have since proven
useful for Maryland narratives too; this module is the shared home so
future adapters don't need to duplicate them.
"""

from __future__ import annotations

import re
from typing import Final

_STREET_TYPE: Final = (
    r"(?:Street|Avenue|Road|Boulevard|Drive|Court|Lane|Place|Way|Highway|Parkway|St|Ave|Rd|Blvd|Dr|Ct|Ln|Pl|Hwy|Pkwy)"
)
_DIR: Final = r"(?:E\.?|W\.?|N\.?|S\.?|North|South|East|West)"


# Pattern 1: "NNNN block of <street>" — e.g. "3200 block of West Colfax".
# The lookahead stops the street capture at a clause boundary so we don't
# absorb half the sentence.
_BLOCK_OF_RE: Final = re.compile(
    r"\b(\d{1,5})\s+block\s+of\s+([A-Z][A-Za-z0-9\s.'-]{2,60}?)(?=[,.\s]+(?:in|when|where|was|on|near|located|at|and|outside|inside|across|behind|by|but|after|during|while)\b|[.,;\r\n]|$)",
    re.IGNORECASE,
)

# Pattern 2: standard street address — "3168 West 14th Avenue".
_STREET_ADDRESS_RE: Final = re.compile(
    rf"\b(\d{{2,5}})\s+(?:({_DIR})\s+)?((?:\d+(?:st|nd|rd|th)|[A-Z][a-zA-Z]+)(?:\s+[A-Z][a-zA-Z]+)?)\s+({_STREET_TYPE})\b"
)

# Pattern 3: full-form intersection — both halves have a street type.
_STREET_FRAG_FULL: Final = (
    rf"(?:(?:{_DIR})\s+)?"
    r"(?:\d+(?:st|nd|rd|th)\s+(?:[A-Z][a-zA-Z]+\s+)?|[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?\s+)"
    rf"{_STREET_TYPE}\b"
)
_INTERSECTION_FULL_RE: Final = re.compile(rf"\b({_STREET_FRAG_FULL})\s+and\s+({_STREET_FRAG_FULL})")

# Pattern 4: short-form intersection — at least one side has the street type.
_STREET_FRAG_SHORT: Final = (
    rf"(?:(?:{_DIR})\s+)?"
    r"(?:\d+(?:st|nd|rd|th)|[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)"
    rf"(?:\s+{_STREET_TYPE})?\b"
)
_INTERSECTION_SHORT_RE: Final = re.compile(
    rf"\b({_STREET_FRAG_SHORT})\s+(?:and|&)\s+({_STREET_FRAG_SHORT})\s+(?:{_STREET_TYPE})s?\b"
)

# Pattern 5: "between X and Y Streets".
_BETWEEN_RE: Final = re.compile(
    rf"\bbetween\s+({_STREET_FRAG_SHORT})\s+and\s+({_STREET_FRAG_SHORT})\s+(?:{_STREET_TYPE})s?\b"
)

# Pattern 6: no-suffix intersection — "43rd and Pecos". Requires an
# explicit trigger word so we don't catch random "X and Y" coordinations.
_ORDINAL: Final = r"\d+(?:st|nd|rd|th)"
_NAMELIKE: Final = r"[A-Z][a-zA-Z]{2,}"
_NOSUFFIX_FRAG: Final = rf"(?:(?:{_DIR})\s+)?(?:{_ORDINAL}|{_NAMELIKE})"
_INTERSECTION_NOSUFFIX_RE: Final = re.compile(
    rf"\b(?:intersection\s+of\s+|at\s+|of\s+)({_NOSUFFIX_FRAG})\s+(?:and|&)\s+({_NOSUFFIX_FRAG})\b"
)

# Pattern 7: lone street near a landmark — "near West Yale Avenue".
_LONE_STREET_RE: Final = re.compile(rf"\b(?:near|along|at|on)\s+({_STREET_FRAG_FULL})")


def _extract_bare(narrative: str) -> str | None:
    """Return the highest-confidence address fragment found, or None.

    Patterns are tried in priority order; the first hit wins. Whitespace
    is collapsed but no city/state context is appended.
    """
    if m := _BLOCK_OF_RE.search(narrative):
        return f"{m.group(1).strip()} {' '.join(m.group(2).split())}"
    if m := _STREET_ADDRESS_RE.search(narrative):
        num, direction, name, stype = m.group(1), m.group(2) or "", m.group(3), m.group(4)
        return f"{num} {direction + ' ' if direction else ''}{name} {stype}".strip()
    if m := _INTERSECTION_FULL_RE.search(narrative):
        return f"{' '.join(m.group(1).split())} and {' '.join(m.group(2).split())}"
    if m := _INTERSECTION_SHORT_RE.search(narrative):
        return " ".join(m.group(0).split())
    if m := _BETWEEN_RE.search(narrative):
        return " ".join(m.group(0).replace("between ", "").split())
    if m := _INTERSECTION_NOSUFFIX_RE.search(narrative):
        return f"{m.group(1)} and {m.group(2)}"
    if m := _LONE_STREET_RE.search(narrative):
        return " ".join(m.group(1).split())
    return None


def extract_address(
    narrative: str | None,
    *,
    city: str | None = None,
    state_code: str | None = None,
) -> str | None:
    """Extract a geocodable address from a narrative.

    Returns the matched address with optional city/state suffix appended
    (comma-separated, in that order). Returns None if no pattern matched.

    Pass `city` and `state_code` together when you want the geocoder to
    anchor on a specific locality (e.g., "1900 Arwell Court, Annapolis,
    MD"). Pass neither for a bare fragment.

    Either argument can be omitted independently — empty/None values are
    silently dropped from the suffix.
    """
    if not narrative:
        return None
    bare = _extract_bare(narrative)
    if bare is None:
        return None

    parts: list[str] = [bare]
    if city:
        parts.append(city.strip())
    if state_code:
        parts.append(state_code.strip())
    return ", ".join(parts)
