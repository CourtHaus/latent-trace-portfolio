"""Parse one NH DOJ Cold Case Unit detail page.

Drupal-rendered HTML. The data we extract:
  - Photo: <img src> + alt; if filename matches a placeholder regex, we
    surface it but the caller skips downloading.
  - Status block: first <p><strong> in body, lines separated by <br>:
        Year of Death or Disappearance: YYYY
        City/Town: <town>
        Status: <Unsolved Homicide | Suspicious Death>
  - Narrative: the <p> immediately after the status block. Trailing "tip
    form" CTAs are NOT included (the CTA is in a SEPARATE <p>; we take
    only the first <p> after status).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from os.path import basename
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from casesignal.etl.services.bs_helpers import attr_str

_PLACEHOLDER_RE = re.compile(
    r"^(female|male|default[_-]social[_-]card|unidentified[_-](?:fe)?male)[._-]",
    re.IGNORECASE,
)

# Status block patterns — applied per-line so a missing <br> separator
# produces honest NULLs rather than one greedy match swallowing the
# whole block.
_YEAR_LABEL = re.compile(r"^Year of Death or Disappearance:\s*(.+?)\s*$", re.IGNORECASE)
_TOWN_LABEL = re.compile(r"^City/Town:\s*(.+?)\s*$", re.IGNORECASE)
_STATUS_LABEL = re.compile(r"^Status:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class DetailContents:
    """Parsed detail-page content."""

    year: str | None
    town: str | None
    status: str | None  # "Unsolved Homicide" | "Suspicious Death" | other
    narrative: str | None
    photo_src: str | None  # absolute or root-relative path
    photo_alt: str | None


def is_placeholder_photo(src: str | None) -> bool:
    """True when the photo URL points at a generic placeholder, not a victim photo."""
    if not src:
        return False
    path = urlparse(src).path or src
    name = basename(path)
    return bool(_PLACEHOLDER_RE.match(name))


def _extract_status_block(soup: BeautifulSoup) -> tuple[str | None, str | None, str | None]:
    """Find the first <p> whose <strong> contains 'Year of Death or Disappearance'.

    The three labels (Year / City/Town / Status) are matched per-line against
    the `<br>`-separated text. If `<br>` separators are missing (malformed
    CMS output) the per-line regexes return None rather than greedily
    swallowing the rest of the block — honest absence over silent garbage.
    """
    for p in soup.find_all("p"):
        text = p.get_text(separator="\n")
        if "Year of Death or Disappearance" not in text:
            continue
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        year = town = status = None
        for line in lines:
            if year is None:
                m = _YEAR_LABEL.match(line)
                if m:
                    year = m.group(1).strip()
                    continue
            if town is None:
                m = _TOWN_LABEL.match(line)
                if m:
                    town = m.group(1).strip()
                    continue
            if status is None:
                m = _STATUS_LABEL.match(line)
                if m:
                    status = m.group(1).strip()
        return year, town, status
    return None, None, None


def _extract_narrative(soup: BeautifulSoup) -> str | None:
    """The <p> immediately after the status block."""
    found_status = False
    for p in soup.find_all("p"):
        text = p.get_text().strip()
        if not text:
            continue
        if "Year of Death or Disappearance" in text:
            found_status = True
            continue
        if not found_status:
            continue
        # Skip the tip-form CTA boilerplate
        if "Tip Form" in text or "Help us solve this case" in text:
            continue
        return text
    return None


def _extract_photo(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Find the victim's primary photo via the CMS `contact_detail_image/` path.

    The CMS always renders this path on detail pages — even the placeholder
    silhouettes (female.jpg/male.jpg) are served via it. Returning None when
    that path is absent is honest absence rather than guessing from leftover
    site chrome (e.g., the state seal at /sites/.../images/seal-no-laurels...).
    """
    for img in soup.find_all("img"):
        src = attr_str(img, "src") or ""
        if not src:
            continue
        if "contact_detail_image" in src or "/styles/contact_detail" in src:
            return src, (attr_str(img, "alt") or None)
    return None, None


def parse_detail(html: str) -> DetailContents:
    soup = BeautifulSoup(html, "html.parser")
    year, town, status = _extract_status_block(soup)
    narrative = _extract_narrative(soup)
    photo_src, photo_alt = _extract_photo(soup)
    return DetailContents(
        year=year,
        town=town,
        status=status,
        narrative=narrative,
        photo_src=photo_src,
        photo_alt=photo_alt,
    )
