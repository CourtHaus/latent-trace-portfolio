"""Parse a DC MPDC year-page (e.g., 2020 unsolved-homicides).

Each year-page lists ~100-200 cases. The page structure uses <p> tags,
one per victim:

    <p>
      <a href="/node/NNNNNN" title="Homicide Victim: Name">
        <img src="...75x56.jpg" />
      </a>
      <a href="/node/MMMMMM" title="Homicide Victim: Name">
        <strong>Victim Name</strong>
      </a>
      \xa0- Month Day, Year; street address, QUADRANT
    </p>

Observed patterns (from 2020 page, 119 cases):
  - Some cases share node IDs between thumbnail and name links; others differ
  - The name link always carries non-empty text; the thumbnail link does not
  - The detail-page node (canonical URL) is the name link's href
  - Date format: "March 9, 2020" (most), "August 2 2020" (no comma, ~5%),
    occasional typos ("Septembet") — all handled by the regex
  - Location: everything after the first semicolon in the paragraph text
  - One intersection-style address: "33rd Street and Dubois Place, SE"
  - "Unit block of N Street, SW" (no numeric prefix)
  - All 2020 cases have both date and location (100% coverage on fixture)

Returns CaseStub objects. The stubs feed into raw_load which then
fetches each case's detail page + PDF flier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

# Match both "Month DD, YYYY" and "Month DD YYYY" (no-comma variant).
# Also tolerates minor typos in month names (e.g., "Septembet").
_DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember|embet)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)

# Homicide Victim link title — allows one-char typos ("Vicim" observed in 2020 data)
_HV_TITLE_RE = re.compile(r"Homicide Vic\w+:", re.IGNORECASE)


@dataclass(frozen=True)
class CaseStub:
    name: str
    detail_url: str
    date_string: str | None
    location: str | None
    thumb_url: str | None


def parse_year_page(html: str, *, base_url: str) -> list[CaseStub]:
    """Walk the year-page <p> blocks; emit CaseStubs for each case.

    Strategy:
      1. Find every <p> that contains at least one link whose title
         matches "Homicide Vic.*:" — this reliably identifies case paragraphs
         while excluding page-nav and language links.
      2. Within each <p>, pick the name link (first <a> with non-empty text).
      3. Parse the paragraph's trailing text for date and location.
      4. Deduplicate by detail_url (in case the same case appears twice).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[CaseStub] = []
    seen_urls: set[str] = set()

    for p in soup.find_all("p"):
        stub = _parse_case_paragraph(p, base_url=base_url)
        if stub is None:
            continue
        if stub.detail_url in seen_urls:
            continue
        seen_urls.add(stub.detail_url)
        out.append(stub)

    return out


def _parse_case_paragraph(p: Tag, *, base_url: str) -> CaseStub | None:
    """Extract a CaseStub from a single <p> block, or return None."""
    links = p.find_all("a", href=True)

    # Must have at least one link with a Homicide Victim-style title
    hv_links = [a for a in links if _HV_TITLE_RE.search(attr_str(a, "title") or "")]
    if not hv_links:
        return None

    # Thumbnail: the img-carrying link (may or may not have text)
    thumb_url: str | None = None
    img = p.find("img")
    if isinstance(img, Tag):
        img_src = attr_str(img, "src")
        if img_src:
            thumb_url = urljoin(base_url, img_src)

    # Name link: first link with non-empty text
    name_link = next(
        (a for a in links if a.get_text().strip()),
        None,
    )
    if name_link is None:
        return None

    name = " ".join(name_link.get_text().split()).strip()
    if not name or len(name) < 3:
        return None

    name_href = attr_str(name_link, "href")
    if name_href is None:
        return None
    detail_url = urljoin(base_url, name_href)

    # Raw text of the whole paragraph for date + location extraction
    raw = p.get_text(separator=" ")
    # Normalize non-breaking spaces and collapse whitespace
    raw = raw.replace("\xa0", " ")
    raw = " ".join(raw.split())

    date_string = _extract_date(raw)
    location = _extract_location_after_semicolon(raw)

    return CaseStub(
        name=name,
        detail_url=detail_url,
        date_string=date_string,
        location=location,
        thumb_url=thumb_url,
    )


def _extract_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    return m.group(0).strip() if m else None


def _extract_location_after_semicolon(text: str) -> str | None:
    """Return the text after the first semicolon, stripped.

    The MPDC format is consistently:  "Name - Date; Location"
    so everything after the semicolon is the location string.
    """
    idx = text.find(";")
    if idx == -1:
        return None
    loc = text[idx + 1 :].strip()
    return loc if loc else None
