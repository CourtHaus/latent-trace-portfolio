"""HTML parsing helpers for the Oklahoma OSBI cold-cases site.

Pure parsing logic — given fetched HTML, extract structured data. No HTTP
here; the polite_http client lives one layer up in adapter.py / raw_load.

Verified site facts (2026-07-08):
- The listing page links 10 alphabetical RANGE pages
  (cold-case-files-{a-b..v-z}.html). Cases are inline blocks ON the range
  pages — there are NO per-case detail URLs.
- Each case is an Adobe Experience Manager (AEM) `cmp-teaser` block:
    <h2 class="cmp-teaser__title"> Victim Name </h2>
    <img ...>  (inside cmp-teaser__image; the case photo)
    <p><b>{Case Type}<br/>{Date}</b></p>
    <p>{narrative}</p> ...
    <p>If you have any information ... contact {OSBI email | local PD phone}</p>
- Every field optional. No case number, no structured age/race/sex/county.
- Served plain HTTP 200 (no Cloudflare); pages + photos share host oklahoma.gov.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

INDEX_URL = (
    "https://oklahoma.gov/osbi/services/investigative-services-division"
    "/cold-case-files/cold-cases.html"
)

_RANGE_HREF_RE = re.compile(r"/cold-case-files-[a-z]-[a-z]\.html$")

_module_logger = logging.getLogger(__name__)


def parse_range_page_links(html: str, base_url: str) -> list[str]:
    """Absolute URLs of the alphabetical range pages, de-duped, doc-ordered."""
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, None] = {}  # dict preserves insertion (document) order
    for a in soup.find_all("a", href=True):
        href = attr_str(a, "href")
        if href is None or not _RANGE_HREF_RE.search(href):
            continue
        seen.setdefault(urljoin(base_url, href), None)
    return list(seen)


_CONTACT_MARKER = "if you have any information"
_CONTACT_PHRASE_RE = re.compile(r"contact\s+the", re.I)
_CONTACT_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
_CONTACT_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


@dataclass(frozen=True)
class OkPhoto:
    source_url: str
    alt: str | None
    filename_hint: str


@dataclass(frozen=True)
class OkCase:
    name: str
    case_type_label: str | None
    date_text: str | None
    narrative: str
    contact_text: str | None
    photo: OkPhoto | None


def _teaser_photo(teaser: Tag, base_url: str) -> OkPhoto | None:
    img = teaser.select_one(".cmp-teaser__image img") or teaser.find("img")
    if img is None:
        return None
    src = attr_str(img, "src")
    if not src:
        return None
    url = urljoin(base_url, src)
    filename = urlparse(url).path.rsplit("/", 1)[-1]
    if not filename:
        return None
    alt = attr_str(img, "alt") or attr_str(img, "title") or None
    return OkPhoto(source_url=url, alt=alt or None, filename_hint=filename)


def parse_range_page(
    html: str,
    *,
    base_url: str = "https://oklahoma.gov/",
    logger: logging.Logger | None = None,
) -> list[OkCase]:
    """Parse every AEM cmp-teaser case block on one range page.

    Per block: title -> name; first <p><b>Type<br/>Date</b></p> -> type+date;
    the paragraph beginning 'If you have any information' -> contact (split off
    the narrative); everything else -> narrative. Every field optional.
    """
    log = logger or _module_logger
    soup = BeautifulSoup(html, "html.parser")
    out: list[OkCase] = []

    for teaser in soup.select(".cmp-teaser"):
        title = teaser.select_one(".cmp-teaser__title")
        name = title.get_text(" ", strip=True) if title is not None else ""
        if not name:
            continue

        case_type_label: str | None = None
        date_text: str | None = None
        # Paragraphs that aren't the bold type/date line, in document order,
        # tagged with whether they look contact-shaped. Only the LAST
        # contact-shaped paragraph is treated as the real contact line
        # (contact is always last); any earlier contact-shaped paragraph
        # falls back to narrative, in its original position.
        body_parts: list[tuple[str, bool]] = []

        desc = teaser.select_one(".cmp-teaser__description")
        paragraphs = desc.select("p") if desc is not None else []
        first_content_paragraph = True
        for p in paragraphs:
            text = p.get_text(" ", strip=True)
            if not text:
                continue
            bold = p.find("b") or p.find("strong")
            # The type/date line is the FIRST NON-EMPTY paragraph and is
            # fully bold. Some teasers put type and date in TWO sibling <b>
            # tags rather than one (e.g. "<b>Suspicious Death<br/></b><b>July
            # 30, 2002</b>"); reading the whole paragraph's text (not just
            # the first <b>) handles both shapes. An empty leading <p></p>
            # (or <p>&nbsp;</p>, stripped to "") must not shift this check
            # to a later paragraph, hence tracking "first content paragraph"
            # rather than raw enumerate() index.
            if first_content_paragraph and bold is not None:
                label, dt = _split_type_date(p)
                case_type_label = label
                date_text = dt
                first_content_paragraph = False
                continue
            first_content_paragraph = False
            body_parts.append((text, _looks_like_contact(text)))

        last_contact_idx = next(
            (i for i in range(len(body_parts) - 1, -1, -1) if body_parts[i][1]), None
        )
        contact_text = body_parts[last_contact_idx][0] if last_contact_idx is not None else None
        narrative_parts = [
            text for i, (text, _) in enumerate(body_parts) if i != last_contact_idx
        ]

        out.append(
            OkCase(
                name=name,
                case_type_label=case_type_label,
                date_text=date_text,
                narrative="\n\n".join(narrative_parts).strip(),
                contact_text=contact_text,
                photo=_teaser_photo(teaser, base_url),
            )
        )

    if not out:
        log.warning("OK OSBI: range page yielded 0 teaser blocks")
    return out


def _looks_like_contact(text: str) -> bool:
    """True if a paragraph reads as the OSBI/local-PD contact line.

    Handles the canonical marker ("If you have any information...") plus
    observed variants like "Anyone with information ... should contact the
    Barnsdall Police Department, phone (918) 847-2285, or
    cold.case@osbi.ok.gov" that don't start with the marker but still name
    an agency/phone/email to reach.
    """
    lowered = text.lower()
    if lowered.startswith(_CONTACT_MARKER):
        return True
    if _CONTACT_PHRASE_RE.search(text):
        return True
    if _CONTACT_EMAIL_RE.search(text) or _CONTACT_PHONE_RE.search(text):
        return True
    return False


def _split_type_date(p: Tag) -> tuple[str | None, str | None]:
    """Split a paragraph's text into (type, date) lines.

    Handles both observed teaser shapes:
      <p><b>Type<br/>Date</b></p>              (one bold, <br/>-separated)
      <p><b>Type<br/></b><b>Date</b></p>        (two sibling bold tags)
    get_text('\\n') preserves the <br/>/tag boundary as a newline in both
    cases; blank lines (e.g. the trailing one left by <br/></b>) are dropped.
    """
    lines = [ln.strip() for ln in p.get_text("\n").split("\n") if ln.strip()]
    label = lines[0] if lines else None
    date_text = lines[1] if len(lines) > 1 else None
    return (label or None), (date_text or None)
