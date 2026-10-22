"""Deterministic offset resolution for LLM-extracted phrases.

Given the source text and a verbatim phrase returned by the LLM, compute
(source_start, source_end, low_confidence). Matching ladder:
  1. strict exact substring (case-sensitive, whitespace-exact)
  2. case-insensitive + whitespace-collapsed — offsets map back to original text
  3. drop with low_confidence=True

No fuzzy / edit-distance matching. Paraphrases get flagged for analyst review
via low_confidence; introducing semantic drift would undermine the "reveal
source" UI's trust contract.
"""

from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def resolve_offsets(
    about_text: str,
    phrase: str | None,
) -> tuple[int, int, bool]:
    """Return (start, end, low_confidence).

    low_confidence=True signals the caller should treat this extraction
    as having no resolvable source span (the classification value may still
    be valid — LLM was confident but paraphrased; UI renders without the
    source-reveal affordance).
    """
    if not phrase or not about_text:
        return 0, 0, True
    if len(phrase) > len(about_text):
        return 0, 0, True

    # Strict: exact substring, case-sensitive.
    idx = about_text.find(phrase)
    if idx >= 0:
        return idx, idx + len(phrase), False

    # Lenient: case-insensitive + whitespace-collapsed. Build a parallel mapping
    # from normalized indices back to original indices so the returned offsets
    # index into the original text.
    normalized_phrase = _WHITESPACE_RE.sub(" ", phrase).lower().strip()
    if not normalized_phrase:
        return 0, 0, True

    normalized_chars: list[str] = []
    original_positions: list[int] = []
    prev_was_space = True  # suppress leading whitespace
    for i, ch in enumerate(about_text):
        if ch.isspace():
            if prev_was_space:
                continue
            normalized_chars.append(" ")
            original_positions.append(i)
            prev_was_space = True
        else:
            normalized_chars.append(ch.lower())
            original_positions.append(i)
            prev_was_space = False
    # Trim any trailing whitespace char emitted above.
    while normalized_chars and normalized_chars[-1] == " ":
        normalized_chars.pop()
        original_positions.pop()
    normalized_text = "".join(normalized_chars)

    idx_norm = normalized_text.find(normalized_phrase)
    if idx_norm < 0:
        return 0, 0, True

    end_norm_exclusive_idx = idx_norm + len(normalized_phrase) - 1
    if end_norm_exclusive_idx >= len(original_positions):
        return 0, 0, True

    start = original_positions[idx_norm]
    end = original_positions[end_norm_exclusive_idx] + 1  # exclusive end
    return start, end, False
