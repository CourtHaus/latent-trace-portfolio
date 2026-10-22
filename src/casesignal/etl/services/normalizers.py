"""Pure-function normalizers shared by ETL adapters.

These helpers were duplicated across the 7 non-MD adapter transforms (and one
scrape module) byte-for-byte. Centralizing them here:

- Removes ~30 LOC of duplication per adapter touching this surface
- Makes correctness improvements (e.g. broader date tolerance, more sentinel
  values) one-change-fixes-everywhere rather than seven
- Tests live alongside this module rather than scattered per-adapter

Pure functions only — no DB, no I/O, no logging. Callers handle persistence.
"""

from __future__ import annotations

import re
from typing import Any

_GENDER_PREFIXES = (("m", "M"), ("f", "F"))

_SENTINEL_VALUES = frozenset(
    {"unknown", "n/a", "none", "not applicable", "not available"}
)

_DATE_MDY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_YEAR_FALLBACK_RE = re.compile(r"\b(19|20)\d{2}\b")


def normalize_gender(raw: str | None) -> str | None:
    """Coerce a raw gender value to the canonical 'M' | 'F' | None.

    Empty / unknown / unparseable → None. First non-whitespace character
    (lowercased) drives the match: any value starting with 'm' → 'M',
    any value starting with 'f' → 'F'. Handles 'Male', 'male', 'M',
    'M.', 'female (suspected)', etc.
    """
    if not raw:
        return None
    g = raw.strip().lower()
    for prefix, canonical in _GENDER_PREFIXES:
        if g.startswith(prefix):
            return canonical
    return None


def normalize_case_type(raw: str | None) -> str | None:
    """Canonicalize a case_type to lowercase snake_case.

    Adapters historically wrote different conventions for the same type
    ('missing-person' vs 'missing_person', 'unidentified-person'). Canonical
    form is lowercase with single '_' separators, matching 'cold_case' /
    'suspicious_death'. Hyphens and whitespace runs collapse to '_'.
    Empty/None → None.
    """
    if not raw:
        return None
    v = re.sub(r"[\s-]+", "_", raw.strip().lower())
    v = re.sub(r"_+", "_", v).strip("_")
    return v or None


def normalize_race(raw: str | None) -> str | None:
    """Normalize race CASING only, preserving distinct categories.

    Source feeds use inconsistent casing ('black'/'Black'/'BLACK',
    'asian'/'ASIAN'). Single-token values are Title-cased to one canonical
    form. Multi-word or punctuated values ('American Indian or Alaska Native',
    'White/Caucasian', 'Black or African American') are left UNCHANGED — those
    are distinct/synonym categories, and merging them is a sensitive
    reclassification of source race data, deliberately out of scope. Whitespace
    is collapsed; empty → None.
    """
    if not raw:
        return None
    s = " ".join(raw.split())
    if not s:
        return None
    if len(s.split()) > 1 or "/" in s or "\\" in s:
        return s
    return s[:1].upper() + s[1:].lower()


def normalize_date(raw: str | None) -> str | None:
    """Convert MM/DD/YYYY (or M/D/YYYY) → YYYY-MM-DD ISO date string.

    On partial input that doesn't match the full MDY pattern, falls back
    to year-only: any 4-digit token starting with 19 or 20 anywhere in
    the input yields '<year>-01-01'. Truly unparseable → None.
    """
    if not raw:
        return None
    m = _DATE_MDY_RE.match(raw.strip())
    if not m:
        ym = _YEAR_FALLBACK_RE.search(raw)
        return f"{ym.group(0)}-01-01" if ym else None
    mm, dd, yyyy = m.groups()
    return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"


def clean_sentinel(raw: str | None) -> str | None:
    """Treat publisher sentinel strings as None for honest absence.

    Sources often write literal 'Unknown' / 'N/A' / '' / 'Not Available' in
    place of NULL. The canonical model represents absence as NULL; converting
    these sentinels at ingest time keeps downstream filter and rendering
    logic simple (no string-equality checks against the various sentinels).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.lower() in _SENTINEL_VALUES:
        return None
    return s


def try_int(raw: Any) -> int | None:
    """Best-effort int coercion. None/empty/non-numeric input → None."""
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return None


def split_victim_name(name: str | None) -> tuple[str, str]:
    """Split a full name into (first_name, last_name).

    Empty / missing input → ('Unknown', ''). Single token → (token, '').
    Multi-token → all but the last token become first_name, last token
    becomes last_name. Whitespace-normalized via str.split().
    """
    if not name:
        return "Unknown", ""
    parts = name.split()
    if not parts:
        return "Unknown", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]
