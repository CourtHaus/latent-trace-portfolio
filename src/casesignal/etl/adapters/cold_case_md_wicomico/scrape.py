"""HTML scraping for the Wicomico County Sheriff cold-cases page.

Index: https://www.wicomicosheriff.com/coldCases (paginated ?page=N).
Card titles for missing-person cases begin 'Missing Person -'; we filter
those out at parse time. Other cards = homicides we ingest.

Detail pages: /coldCases/<24-char-hex-objectid>. Stable hex ID is used
directly as source_case_id.

The detail page is rendered by a Next.js App Router app (OCV platform).
Case content is delivered via ``self.__next_f.push`` script tags in two
forms:

1. The *item* script: a key-prefixed RSC node
   ``"<hex>:[\\"$\\",\\"$L25\\",null,{item:{_id,title,content,images}}]"``
   where ``content`` is either raw HTML *or* a ``"$<N>"`` reference.

2. When content is a reference (``"$<N>"``), a second script pushes raw
   HTML directly: ``[1, "<p>INCIDENT: ...</p>\\r\\n..."]`` (no key prefix).

``parse_detail`` handles both forms.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

logger = logging.getLogger(__name__)

_MISSING_PREFIX_RE = re.compile(r"^\s*missing\s+person\s*[-–—]\s*", re.IGNORECASE)
# Recognized "no-prefix" or known-acceptable formats; anything else is
# logged as an unknown prefix for human review.
_KNOWN_BARE_NAME_RE = re.compile(
    r"^[A-Z][A-Za-z'.\-]*(?:\s+[A-Z][A-Za-z'.\-]*)+(?:\s+(?:Jr\.?|Sr\.?|II|III|IV))?$"
)
_OBJECTID_RE = re.compile(r"^[0-9a-f]{24}$", re.IGNORECASE)
_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_FILENAME_MAX_LEN = 100


@dataclass(frozen=True)
class CaseRef:
    """Index-level reference to one Wicomico County case detail page."""

    case_name: str
    detail_url: str
    source_case_id: str  # 24-char hex ObjectId


def parse_index_page(html: str, *, base_url: str) -> list[CaseRef]:
    """Parse one page of the Wicomico cold-case index.

    - Drops cards whose title starts 'Missing Person -' (case-insensitive,
      tolerant of -, en-dash, em-dash).
    - Keeps cards with unrecognized prefixes but emits a warning so we
      notice new patterns (transform-time defensive check covers them).
    - Pagination is the caller's responsibility (call once per ?page=N).
    """
    soup = BeautifulSoup(html, "html.parser")
    refs: list[CaseRef] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = (attr_str(a, "href") or "").strip()
        if not href:
            continue
        if "/coldCases/" not in href:
            continue
        # Discard the index-page link itself.
        slug = _slug_from_url(urljoin(base_url, href))
        if not _OBJECTID_RE.match(slug):
            continue

        title = _title_from_card(a)
        if not title:
            continue

        if _MISSING_PREFIX_RE.match(title):
            logger.info(
                "wicomico.skip_missing_person",
                extra={"title": title, "slug": slug},
            )
            continue

        if not _KNOWN_BARE_NAME_RE.match(title):
            logger.warning(
                "wicomico.unknown_title_prefix",
                extra={"title": title, "slug": slug},
            )

        if slug in seen:
            continue
        seen.add(slug)
        refs.append(
            CaseRef(
                case_name=title,
                detail_url=urljoin(base_url, href),
                source_case_id=slug,
            )
        )
    return refs


def _slug_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]


def _title_from_card(a: Tag) -> str:
    """Extract a single-line card title from the link element.

    Wicomico's actual structure: <a href="..."><h2>Name</h2></a>.
    Prefer an inner element whose class contains 'title' (handles
    synthetic test fixtures with class='card-title'), falling back to
    the full link text (handles the real site's <h2> structure).
    """
    title_el = a.find(class_=lambda c: c and "title" in " ".join(c).lower())
    text = title_el.get_text() if title_el is not None else a.get_text()
    return " ".join(text.split()).strip()


def sanitize_filename(raw: str) -> str | None:
    if not raw:
        return None
    cleaned = _FILENAME_SANITIZE_RE.sub("_", raw).lstrip(".").replace("\x00", "")
    if not cleaned:
        return None
    if len(cleaned) > _FILENAME_MAX_LEN:
        if "." in cleaned[-10:]:
            stem, dot, ext = cleaned.rpartition(".")
            keep = _FILENAME_MAX_LEN - len(dot) - len(ext)
            cleaned = (stem[:keep] + dot + ext) if keep > 0 else cleaned[:_FILENAME_MAX_LEN]
        else:
            cleaned = cleaned[:_FILENAME_MAX_LEN]
    return cleaned


# ── Detail-page extraction ────────────────────────────────────────────────────


@dataclass(frozen=True)
class CaseDetail:
    """Per-case detail-page parse result."""

    narrative_text: str
    photo_url: str | None
    photo_filename: str | None
    photo_alt_text: str | None


_HOMICIDE_TERMS = (
    "homicide",
    "murder",
    "killed",
    "shot to death",
    "stabbed to death",
    "beaten to death",
)
_MISSING_TERMS = (
    "missing since",
    "last seen",
    "has been missing",
    "endangered missing",
)

# Next.js RSC stream: key-prefixed nodes look like "hexkey:json_value"
_RSC_KEY_RE = re.compile(r"^([0-9a-f]+):(.+)$", re.DOTALL | re.IGNORECASE)
# Boilerplate paragraph prefixes to skip when building the narrative.
_BOILERPLATE_RE = re.compile(
    r"^(incident|date|location|narrative)\s*:",
    re.IGNORECASE,
)
# Substrings that indicate tip-line content anywhere in a paragraph.
_TIPLINE_MARKERS = (
    "anyone with information",
    "crime solvers",
    "crime stoppers",
    "tip line",
    "if you have any information",
)


def _strip_tipline_suffix(paragraph_text: str) -> str:
    """If a paragraph contains tip-line text mid-paragraph, truncate at the
    SENTENCE that introduces it.  Keeps narrative before the tip-line sentence;
    drops everything from that sentence onward.

    Returns the cleaned text, or "" if the tip-line occupies the first sentence
    (i.e. there is no narrative prefix to keep).
    """
    lower = paragraph_text.lower()
    earliest = len(paragraph_text)
    for marker in _TIPLINE_MARKERS:
        idx = lower.find(marker)
        if idx != -1 and idx < earliest:
            earliest = idx
    if earliest == len(paragraph_text):
        return paragraph_text  # no tip-line found

    # Walk backward from the marker to find the start of its sentence.
    # A sentence boundary is: '.' / '!' / '?' followed by whitespace.
    # If no boundary is found, drop the whole paragraph (top-to-bottom tip-line).
    prefix = paragraph_text[:earliest].rstrip()
    last_period = max(prefix.rfind(". "), prefix.rfind("! "), prefix.rfind("? "))
    if last_period == -1:
        # Fallback: bare period at end of prefix (no following whitespace).
        # Handles CMS quirks like "He was shot.Anyone with information..."
        last_period = max(prefix.rfind("."), prefix.rfind("!"), prefix.rfind("?"))
    if last_period == -1:
        # Marker is in the only sentence — drop the whole paragraph.
        return ""
    return prefix[: last_period + 1].strip()


def _extract_rsc_case_data(soup: BeautifulSoup) -> tuple[str, list[dict[str, Any]]]:
    """Pull case content HTML + image list from Next.js RSC script tags.

    The OCV/Next.js platform delivers case data via ``self.__next_f.push``
    scripts in one of two forms:

    * *Item script*: a key-prefixed RSC node whose decoded JSON is a list
      ``["$", "$L25", null, {"item": {_id, title, content, images}}]``.
      If ``content`` is a ``"$N"`` reference it is resolved from a second
      script.
    * *Content script*: ``[1, "<p>…</p>…"]`` — raw HTML with no key prefix.
      This is emitted when the content was too large (or is a streamed
      reference) to inline in the item script.

    Returns ``(content_html, images)`` where *images* is the list of dicts
    from the item payload (may be empty).
    """
    item_data: dict[str, Any] | None = None
    direct_html: str | None = None

    for s in soup.find_all("script"):
        text = s.string or ""
        if not text or "__next_f" not in text:
            continue
        # Match self.__next_f.push([1, "..."])  (the trailing ) may follow \n)
        m = re.match(r"self\.__next_f\.push\((\[.*)\)\s*$", text.strip(), re.DOTALL)
        if not m:
            continue
        try:
            arr = json.loads(m.group(1))
        except Exception:
            continue
        if len(arr) < 2 or not isinstance(arr[1], str):
            continue
        val: str = arr[1]

        # Raw HTML push (no key prefix — starts with "<")
        if val.startswith("<"):
            direct_html = val
            continue

        # Key-prefixed RSC node
        km = _RSC_KEY_RE.match(val)
        if not km:
            continue
        rest = km.group(2)
        try:
            obj = json.loads(rest)
        except Exception:
            continue
        # RSC component node: ["$", "$L25", null, {item: {...}}]
        if (
            isinstance(obj, list)
            and len(obj) >= 4
            and isinstance(obj[3], dict)
            and "item" in obj[3]
        ):
            candidate = obj[3]["item"]
            if isinstance(candidate, dict) and "_id" in candidate and "title" in candidate:
                item_data = candidate

    if item_data is None:
        return "", []

    images: list[dict[str, Any]] = item_data.get("images") or []
    content = item_data.get("content", "") or ""

    # If content is a "$N" reference, use the separately-streamed HTML.
    if content.startswith("$") and direct_html is not None:
        content = direct_html

    return content, images


def _narrative_from_html(content_html: str) -> str:
    """Extract a clean narrative string from the case content HTML.

    Strips INCIDENT/DATE/LOCATION/NARRATIVE label paragraphs and
    tip-line boilerplate. Handles the case where a single paragraph fuses
    narrative text with tip-line text — truncates at the sentence that
    introduces the tip-line content rather than dropping the whole paragraph.
    """
    soup = BeautifulSoup(content_html, "html.parser")
    parts: list[str] = []
    for p in soup.find_all("p"):
        text = " ".join(p.get_text().split()).strip()
        if not text or len(text) < 10:
            continue
        if _BOILERPLATE_RE.match(text):
            continue
        lower = text.lower()
        # Pure tip-line paragraphs — drop entirely.
        if lower.startswith(("contact", "if you have")):
            continue
        # Strip tip-line suffix from fused paragraphs (or drop entirely if
        # the tip-line occupies the first sentence).
        text = _strip_tipline_suffix(text)
        if not text or len(text) < 20:
            continue
        if text in parts:
            continue
        parts.append(text)
    return " ".join(parts).strip()


def parse_detail(html: str, *, case_ref_url: str) -> CaseDetail:
    """Parse a Wicomico cold-case detail page.

    Extracts the narrative (joined visible <p> text minus boilerplate)
    and primary photo URL + alt text.

    The Wicomico site is a Next.js App Router app (OCV platform) that
    delivers case data via ``self.__next_f.push`` RSC stream scripts
    rather than static HTML. ``_extract_rsc_case_data`` handles both the
    inline-content and reference-content variants.
    """
    soup = BeautifulSoup(html, "html.parser")
    content_html, images = _extract_rsc_case_data(soup)
    narrative = _narrative_from_html(content_html)

    photo_url: str | None = None
    photo_filename: str | None = None
    photo_alt: str | None = None

    if images:
        # Prefer the "large" variant of the first image entry.
        first = images[0]
        src = first.get("large") or first.get("small") or ""
        if src:
            photo_url = urljoin(case_ref_url, src)
            raw_name = urlparse(photo_url).path.rsplit("/", 1)[-1]
            photo_filename = sanitize_filename(raw_name)
            # OCV images don't carry alt text in the JSON; leave None.

    return CaseDetail(
        narrative_text=narrative,
        photo_url=photo_url,
        photo_filename=photo_filename,
        photo_alt_text=photo_alt,
    )


def looks_like_missing_person(narrative: str) -> bool:
    """Defensive: detect missing-person framing in detail-page narrative.

    Returns True iff the narrative mentions a missing-person term AND does
    NOT mention any homicide term. The homicide-term override prevents
    false positives on cases where a victim was last seen before being
    killed ("he was last seen leaving work before being shot").

    Used by transform.py as a second-line filter after the index-page
    ``_MISSING_PREFIX_RE`` check.
    """
    lower = narrative.lower()
    if not any(term in lower for term in _MISSING_TERMS):
        return False
    if any(term in lower for term in _HOMICIDE_TERMS):
        return False
    return True
