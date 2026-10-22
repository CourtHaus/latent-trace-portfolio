from __future__ import annotations

import re

# A "sentence-shaped" title is long enough to be prose and/or ends in a period
# and/or starts lowercase. Real FDLE titles are short proper-noun phrases
# ("Jennifer Kesse Missing Person Case"); summaries dumped into the title field
# read like prose.
_SENTENCE_MIN_WORDS = 8

# Street-number + street-word pattern, e.g. "10207 SW 84 Ave", "500 W Robinson St".
# Also matches "11000 block" (block-number references common in police narratives).
_ADDRESS_RE = re.compile(
    r"\b\d{2,6}\s+[\w.]+(?:\s+[\w.]+){0,3}\s+"
    r"(?:st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ln|lane|"
    r"ct|court|way|hwy|highway|pl|place|cr|circle|trail|trl|block)\b",
    re.IGNORECASE,
)

# Dates: "January 24, 2006" or numeric "12-04-06" / "01/24/2006".
_DATE_RE = re.compile(
    r"\b("
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r")\b",
    re.IGNORECASE,
)

_SENTINELS = {"", ",", ".", "-", "n/a", "na", "unknown", "none"}


def _norm(text: str | None) -> str:
    return (text or "").strip()


def is_sentence_shaped(text: str | None) -> bool:
    """Calibrated for the FDLE ``case_title`` field: a real title is a short
    proper-noun phrase, so prose-like length or a lowercase lead-in signals a
    summary that leaked into the title. Do NOT reuse against narrative/about
    text — the lowercase rule would hit nearly everything there.
    """
    value = _norm(text)
    if not value:
        return False
    if value.endswith(")"):
        # Real FDLE titles end with the agency tag, e.g. "... (Alachua CSO)";
        # a leaked summary ends in prose punctuation. This keeps legit long
        # multi-victim titles ("...Homicides (Clearwater PD)") from being flagged.
        # Mirrors cold_case_fl_fdle/transform.py:_is_sentence_shaped — keep in sync.
        return False
    word_count = len(value.split())
    if word_count >= _SENTENCE_MIN_WORDS:
        return True
    # Short strings: prose tells include a trailing period on a multi-word, or a
    # lowercase first letter (proper titles capitalize).
    if word_count >= 3 and value.endswith("."):
        return True
    if value[:1].islower():
        return True
    return False


def name_would_reverse(name: str | None) -> bool:
    """True when `_split_fdle_name` will produce first/last in the WRONG order.

    FDLE supplies "Last, First". With a comma the adapter splits correctly.
    Without a comma it splits on whitespace and treats the LAST token as the
    surname — which silently reverses a "First Last" string.
    """
    value = _norm(name)
    if "," in value:
        return False
    tokens = value.split()
    return len(tokens) >= 2


def is_sentinel_address(addr: str | None) -> bool:
    lowered = _norm(addr).lower()
    stripped = lowered.strip(" ,.-")
    return lowered in _SENTINELS or stripped == ""


def narrative_has_address(text: str | None) -> bool:
    return bool(_ADDRESS_RE.search(_norm(text)))


def text_has_date(text: str | None) -> bool:
    return bool(_DATE_RE.search(_norm(text)))
