"""Minnesota BCA Summary-of-Case (SOC) PDF parser.

Extracts, from the single-page text layer (pdfplumber):
  - narrative: the `Details:` text, the input for Tier-1/Tier-2 extraction
  - sex / race: best-effort, ONLY when both are clean single tokens
    (multi-victim PDFs carry compound values that cannot be attributed
    per-victim -- those are deferred to Tier-2)
  - contact_agency / contact_phone: from the closing
    "If you have any information ... please contact <AGENCY> at <PHONE>."

Per the cold-case-adapter convention, this never raises on a parse
failure -- it returns SocContents with None/empty fields and lets the
caller decide on fallbacks.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SocContents:
    narrative: str
    sex: str | None
    race: str | None
    contact_agency: str | None
    contact_phone: str | None


_EMPTY = SocContents(
    narrative="", sex=None, race=None, contact_agency=None, contact_phone=None
)

# Narrative: everything after "Details:" up to the closing contact line.
_NARRATIVE_RE = re.compile(
    r"Details:\s*(.+?)\s*If you have any information",
    re.IGNORECASE | re.DOTALL,
)
# Contact line: "...please contact [the] <AGENCY> at <PHONE>." The phone may
# wrap a newline, so the capture tolerates internal whitespace. The trailing
# period is optional — pdfplumber occasionally drops it on a wrapped line.
_CONTACT_RE = re.compile(
    r"please contact\s+(?:the\s+)?(.+?)\s+at\s+([0-9][0-9\s\-]+[0-9])\s*(?:\.|$)",
    re.IGNORECASE | re.DOTALL,
)
# Sex/Race values, captured up to the next known label or end of line.
_SEX_RE = re.compile(r"Sex:\s*(.+?)(?:\s+Originating Agency:|\s+Race:|\n|$)", re.IGNORECASE)
_RACE_RE = re.compile(r"Race:\s*(.+?)(?:\s+Originating Agency:|\s+Details:|\n|$)", re.IGNORECASE)
# A clean single-token sex value.
_SIMPLE_SEX_RE = re.compile(r"^(?:male|female)$", re.IGNORECASE)
# A clean single-word race value. Intentionally conservative: letters only,
# no hyphens or spaces — that excludes compound multi-victim strings. Values
# like "Native American" fall through to None and are filled by Tier-2.
_SIMPLE_RACE_RE = re.compile(r"^[A-Za-z]+$")


def parse_soc_pdf(pdf_path: Path) -> SocContents:
    """Parse a SOC PDF. Returns SocContents; never raises."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return _EMPTY
            text = pdf.pages[0].extract_text() or ""
    except Exception as exc:  # noqa: BLE001 -- parse failure must not abort the run
        logger.warning("pdfplumber failed on %s: %r", pdf_path, exc)
        return _EMPTY

    narrative = _extract_narrative(text)
    sex, race = _extract_sex_race(text)
    agency, phone = _extract_contact(text)
    return SocContents(
        narrative=narrative,
        sex=sex,
        race=race,
        contact_agency=agency,
        contact_phone=phone,
    )


def _extract_narrative(text: str) -> str:
    m = _NARRATIVE_RE.search(text)
    if not m:
        return ""
    # Collapse the internal newlines pdfplumber inserts at wrap points.
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _extract_sex_race(text: str) -> tuple[str | None, str | None]:
    """Return (sex, race) only when sex is a clean single token.

    A compound Sex: value means the PDF describes multiple victims and
    neither field can be attributed per-victim -- defer both to Tier-2.
    """
    sex_m = _SEX_RE.search(text)
    if sex_m is None:
        return None, None
    sex_raw = sex_m.group(1).strip()
    if not _SIMPLE_SEX_RE.match(sex_raw):
        return None, None  # compound / multi-victim -> defer both

    sex = sex_raw.capitalize()
    race: str | None = None
    race_m = _RACE_RE.search(text)
    if race_m is not None:
        race_raw = race_m.group(1).strip()
        if _SIMPLE_RACE_RE.match(race_raw):
            race = race_raw.capitalize()
    return sex, race


def _extract_contact(text: str) -> tuple[str | None, str | None]:
    m = _CONTACT_RE.search(text)
    if m is None:
        return None, None
    agency = re.sub(r"\s+", " ", m.group(1)).strip() or None
    phone = re.sub(r"\s+", "", m.group(2)) or None
    return agency, phone
