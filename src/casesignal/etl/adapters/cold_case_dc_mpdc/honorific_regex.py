"""Gender inference from narrative honorifics.

Per feedback_demographic_inference_rules memory: extracting gender
from explicit narrative-text honorifics is acceptable because the
source-author wrote them. Inferring gender from a person's name
alone is NEVER acceptable.

DC's MPDC bulletins consistently use Mr./Mrs./Ms./Miss honorifics in
the "DESCRIPTION OF INCIDENT" sentence. About 90%+ of MPDC narratives
carry an honorific (estimate from spike; real number measured at
ingestion).
"""

from __future__ import annotations

import re

_HONORIFIC_GENDER_RE = re.compile(
    r"\b(Mr|Mrs|Ms|Miss|Mx)\.?\s+",
    re.IGNORECASE,
)


_HONORIFIC_GENDER_MAP: dict[str, str | None] = {
    "mr": "M",
    "mrs": "F",
    "ms": "F",
    "miss": "F",
    "mx": None,  # gender-neutral; we don't fabricate M/F
}


def infer_gender_from_honorific(narrative: str) -> str | None:
    """Return 'M' / 'F' / None based on the FIRST honorific in the text.

    Returns None when no honorific is found OR when the honorific is
    'Mx.' (gender-neutral; we don't guess).
    """
    if not narrative:
        return None
    m = _HONORIFIC_GENDER_RE.search(narrative)
    if m is None:
        return None
    return _HONORIFIC_GENDER_MAP.get(m.group(1).lower())
