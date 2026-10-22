"""DC MPDC reward-flier PDF parser.

Extracts CCN + Public Bulletin Number + reward amount + detective
contacts from the text layer (pdfplumber). Victim photo (photo_bytes +
photo_content_type) extracted from page-1 image XObjects via pikepdf
(Task B3).

Per design: never raises on parse failure — returns FlierContents
with None / empty fields. Callers in raw_load decide whether to
fall back (slug-id for missing CCN, index thumbnail for missing
photo, default contact row for missing detectives).

Notes on the MPDC flier text layout (from pdfplumber extraction):
- "Public Bulletin No. 2022-HOM-042622A Ref. CCN:" appears on one
  line but the CCN value is NOT adjacent — it lands near the bottom
  of the extracted text (line ~40) as a bare "22-057-404" string.
  Matching it as a standalone \\d{2}-\\d{3}-\\d{3} is the only reliable
  approach.
- "Up to" and "$25,000 Reward" appear on separate lines.  Match
  "$25,000 Reward" directly rather than anchoring to "Up to".
- Detective contact lines are self-contained:
    "Detective Kurt Hansen (202) 815-1248 cell"

Notes on image XObjects (from pikepdf probe):
- Page 1 of the sample flier has 6 images; 5 are tiny icons (≤32x32).
- /Im5 at 1044x1044 is the victim photo (DCTDecode = JPEG).
- _extract_largest_image() filters below _MIN_PHOTO_PIXEL_AREA and
  returns raw encoded bytes for the largest qualifying image.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
import pikepdf

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectiveContact:
    name: str  # "Detective Kurt Hansen"
    phone: str  # "(202) 815-1248"
    role: str | None = None  # "cell" / "main" / None


@dataclass(frozen=True)
class FlierContents:
    ccn: str | None
    public_bulletin_no: str | None
    photo_bytes: bytes | None
    photo_content_type: str | None
    detective_contacts: list[DetectiveContact] = field(default_factory=list)
    reward_amount: int | None = None


_BULLETIN_NO_RE = re.compile(
    r"Public Bulletin No\.?\s*(\d{4}-HOM-[A-Z0-9]+)",
    re.IGNORECASE,
)
# CCN value appears as a standalone "NN-NNN-NNN" near the bottom of the
# pdfplumber text output (the "Ref. CCN:" label is on an earlier line
# with no adjacent value due to multi-column layout).
_CCN_RE = re.compile(r"\b(\d{2}-\d{3}-\d{3})\b")

# Reward amount: "$25,000 Reward" appears directly in the text.
_REWARD_RE = re.compile(
    r"\$([\d,]+)\s*Reward",
    re.IGNORECASE,
)
# One contact line: "Detective <Name> (NNN) NNN-NNNN [role]"
# Non-greedy name capture stops at the first phone number prefix.
_CONTACT_LINE_RE = re.compile(
    r"(Detective\s+[A-Za-z][A-Za-z\s.\'-]*?)\s+(\(\d{3}\)\s*\d{3}-\d{4})"
    r"(?:\s+(cell|main|day|night|office))?",
    re.IGNORECASE,
)
# "Homicide Branch (NNN) NNN-NNNN main"
_HOMICIDE_BRANCH_RE = re.compile(
    r"(Homicide Branch)\s+(\(\d{3}\)\s*\d{3}-\d{4})\s*(main)?",
    re.IGNORECASE,
)


def parse_flier(pdf_path: Path) -> FlierContents:
    """Extract structured data from an MPDC reward flier.

    Text fields (CCN, bulletin no., reward, detective contacts) come
    from pdfplumber. Victim photo (photo_bytes, photo_content_type)
    comes from pikepdf image XObject extraction.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            text = page.extract_text() or ""
    except Exception as exc:
        logger.warning("pdfplumber failed on %s: %r", pdf_path, exc)
        return FlierContents(
            ccn=None,
            public_bulletin_no=None,
            photo_bytes=None,
            photo_content_type=None,
            detective_contacts=[],
            reward_amount=None,
        )

    ccn = _extract_first(text, _CCN_RE)
    bulletin_no = _extract_first(text, _BULLETIN_NO_RE)
    reward = _extract_reward(text)
    contacts = _extract_contacts(text)

    # Image extraction via pikepdf (largest image on page 1 = victim photo)
    photo_bytes, photo_content_type = _extract_largest_image(pdf_path)

    return FlierContents(
        ccn=ccn,
        public_bulletin_no=bulletin_no,
        photo_bytes=photo_bytes,
        photo_content_type=photo_content_type,
        detective_contacts=contacts,
        reward_amount=reward,
    )


def _extract_first(text: str, pattern: re.Pattern[str]) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None


def _extract_reward(text: str) -> int | None:
    m = _REWARD_RE.search(text)
    if m is None:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _extract_contacts(text: str) -> list[DetectiveContact]:
    """Walk all detective + homicide-branch lines in the text."""
    contacts: list[DetectiveContact] = []
    for m in _CONTACT_LINE_RE.finditer(text):
        contacts.append(
            DetectiveContact(
                name=m.group(1).strip(),
                phone=m.group(2).strip(),
                role=(m.group(3).strip().lower() if m.group(3) else None),
            )
        )
    for m in _HOMICIDE_BRANCH_RE.finditer(text):
        contacts.append(
            DetectiveContact(
                name=m.group(1).strip(),
                phone=m.group(2).strip(),
                role="main",
            )
        )
    return contacts


# Heuristic: ignore tiny logos (badges, QR codes, brand marks). Victim
# photos on MPDC fliers are typically >=150x150. We keep the LARGEST
# image above this threshold.
_MIN_PHOTO_PIXEL_AREA = 100 * 100


def _extract_largest_image(pdf_path: Path) -> tuple[bytes | None, str | None]:
    """Walk page-1 images; return raw bytes + content_type for the
    largest one above _MIN_PHOTO_PIXEL_AREA. Returns (None, None) if
    no qualifying image found.
    """
    try:
        with pikepdf.open(pdf_path) as pdf:
            if not pdf.pages:
                return (None, None)
            images = pdf.pages[0].images
            if not images:
                return (None, None)

            best: tuple[int, bytes, str] | None = None  # (area, bytes, mime)
            for _name, image in images.items():
                try:
                    pdf_image = pikepdf.PdfImage(image)
                    w = pdf_image.width
                    h = pdf_image.height
                    area = w * h
                    if area < _MIN_PHOTO_PIXEL_AREA:
                        continue
                    if best is not None and area <= best[0]:
                        continue
                    raw = pdf_image.obj.read_raw_bytes()
                    mime = _content_type_from_filter(pdf_image)
                    best = (area, raw, mime)
                except Exception as exc:
                    logger.info("pikepdf image probe failed: %r", exc)
                    continue

            if best is None:
                return (None, None)
            return (best[1], best[2])
    except Exception as exc:
        logger.warning("pikepdf failed on %s: %r", pdf_path, exc)
        return (None, None)


def _content_type_from_filter(pdf_image: pikepdf.PdfImage) -> str:
    """Map pikepdf image filter to MIME type.

    DCTDecode = JPEG, FlateDecode = PNG-ish, JBIG2/CCITTFax = TIFF-ish.
    For our use, anything non-JPEG falls through to image/png as a
    safe-ish default (the bytes are still PDF-stream-encoded; the
    consumer would need to convert via Pillow if they want a real
    PNG). The extracted bytes are saved to disk; re-encoding is a
    Phase 1.8b concern if the photos look broken in the UI.
    """
    try:
        filters = pdf_image.filters
    except AttributeError:
        # Older pikepdf API
        filters = getattr(pdf_image.obj, "Filter", None)

    if filters is None:
        return "image/png"
    filter_names: list[str] = []
    if hasattr(filters, "__iter__") and not isinstance(filters, str):
        filter_names = [str(f) for f in filters]
    else:
        filter_names = [str(filters)]
    if any("DCTDecode" in n for n in filter_names):
        return "image/jpeg"
    return "image/png"
