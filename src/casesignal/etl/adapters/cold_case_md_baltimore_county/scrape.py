"""HTML scraping helpers for the Baltimore County PD unsolved-homicides site.

Pure parsing logic — given fetched HTML, extract the structured fields
we need. No HTTP calls here; the polite_http client lives one layer up
in adapter.py / load_raw.

Decisions:

- The list page has a clean "all detail pages on one URL" structure;
  we extract URLs by CSS selector
  `a[href^="/departments/police/unsolved/homicides/"]` minus the index
  URL itself.
- Each URL slug carries the source_case_id (e.g. `andre-gay-2008`).
- Detail pages are Drupal-generated; field layout is consistent across
  the 78 cases we sampled.
- Multi-victim cases are NOT detected by slug-shape heuristics (those
  are fragile — `mary-ann-smith-2003` looks multi-victim but isn't);
  instead, an explicit allowlist of `MULTI_VICTIM_SOURCE_CASE_IDS`
  enumerates the known multi-victim slugs from the 78-case set.
- Filename sanitization for downloaded photos lives here too — we
  strip path separators, leading dots, null bytes, and any character
  outside `[A-Za-z0-9._-]`; truncate to 100 chars; reject if empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from casesignal.etl.services.bs_helpers import attr_str

# Multi-victim cases from the 78-case BCounty corpus. Single-victim is the
# default; cases listed here produce multiple victim rows on transform.
# Populated by inspection of the live index — Phase 1 ships with these
# four; future scrapes (Phase 1.x) may add more if the source updates.
MULTI_VICTIM_SOURCE_CASE_IDS: frozenset[str] = frozenset(
    {
        "gericke-victoria-gericke-mary-1992",
        # Other multi-victim slugs to add during impl after a full pass over
        # the 78-case set; for Phase 1 this single confirmed case is the
        # working list.
    }
)


_DETAIL_HREF_RE = re.compile(r"^/departments/police/unsolved/homicides/(?P<slug>[^/?#]+)/?$")
_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_FILENAME_MAX_LEN = 100


@dataclass(frozen=True)
class DetailPageFields:
    """Parsed fields from a single detail page."""

    case_name: str
    case_year: int | None
    narrative_text: str
    photo_filename: str | None  # sanitized; ready to write to disk
    photo_content_type: str | None  # guessed from extension; verified on download
    photo_alt_text: str | None
    photo_source_url: str | None  # absolute URL to fetch


def parse_index_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return [(detail_url, source_case_id), ...] from the list page.

    `base_url` is the absolute URL the list page was fetched from; relative
    `<a href>` values are resolved against it.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, str] = {}  # source_case_id -> absolute_url; dedupe
    for a in soup.find_all("a", href=True):
        href = attr_str(a, "href")
        if href is None:
            continue
        m = _DETAIL_HREF_RE.match(href)
        if not m:
            continue
        slug = m.group("slug")
        if slug in out:
            continue
        absolute = urljoin(base_url, href)
        out[slug] = absolute
    return [(url, slug) for slug, url in sorted(out.items())]


def parse_detail_page(html: str, *, base_url: str) -> DetailPageFields:
    """Parse a single detail page into its structured fields.

    Raises ValueError if required fields (case_name, narrative_text) can't
    be extracted — that's a signal the page structure changed and the
    scraper needs updating.
    """
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.select_one("h1.c-page-title")
    if h1 is None:
        raise ValueError("detail page missing h1.c-page-title")
    case_name = " ".join(h1.get_text().split()).strip()
    if not case_name:
        raise ValueError("detail page h1.c-page-title is empty")

    # Narrative + h2 header live inside the c-wysiwyg field block.
    wysiwyg = soup.select_one(".c-wysiwyg .c-field__content") or soup.select_one(".c-wysiwyg")
    if wysiwyg is None:
        raise ValueError("detail page missing .c-wysiwyg content block")

    h2 = wysiwyg.find("h2")
    case_year = _extract_year_from_header(h2.get_text() if h2 else None)

    # Narrative is the first <p> in the wysiwyg block; a detail page may
    # have multiple paragraphs (REWARD OFFERED, history sections), but
    # the case narrative is reliably the first one.
    paragraphs = wysiwyg.find_all("p")
    narrative_text = ""
    for p in paragraphs:
        text = " ".join(p.get_text().split())
        if not text:
            continue
        # Skip sections we know aren't the case narrative.
        if text.lower().startswith("anyone with information"):
            continue
        narrative_text = text
        break

    if not narrative_text or len(narrative_text) < 50:
        raise ValueError(
            f"detail page narrative too short or missing" f" (got {len(narrative_text)} chars)"
        )

    # Photo — figure.c-figure--image > img if present
    img = soup.select_one("figure.c-figure--image img") or soup.select_one(".c-wysiwyg img")
    photo_filename = None
    photo_content_type = None
    photo_alt_text = None
    photo_source_url = None
    if img is not None and (img_src := attr_str(img, "src")):
        absolute_src = urljoin(base_url, img_src)
        # Strip query string before computing filename
        parsed = urlparse(absolute_src)
        raw_filename = parsed.path.rsplit("/", 1)[-1]
        photo_filename = sanitize_filename(raw_filename)
        if photo_filename:
            photo_content_type = _content_type_from_filename(photo_filename)
            photo_alt_text = attr_str(img, "alt") or None
            photo_source_url = absolute_src

    return DetailPageFields(
        case_name=case_name,
        case_year=case_year,
        narrative_text=narrative_text,
        photo_filename=photo_filename,
        photo_content_type=photo_content_type,
        photo_alt_text=photo_alt_text,
        photo_source_url=photo_source_url,
    )


def _extract_year_from_header(header_text: str | None) -> int | None:
    """Pull a year from headers like 'HOMICIDE VICTIM, 2008' or
    'Homicide Victim, 1992'."""
    if not header_text:
        return None
    m = re.search(r"\b(19|20)\d{2}\b", header_text)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def _content_type_from_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")


def sanitize_filename(raw: str) -> str | None:
    """Strip path separators, leading dots, null bytes, anything outside
    [A-Za-z0-9._-]. Truncate to _FILENAME_MAX_LEN. Return None if empty.
    """
    if not raw:
        return None
    # Replace forbidden chars with underscore (safer than dropping chars
    # which can collide).
    cleaned = _FILENAME_SANITIZE_RE.sub("_", raw)
    cleaned = cleaned.lstrip(".")  # disallow leading dots (no .htaccess etc.)
    cleaned = cleaned.replace("\x00", "")
    if not cleaned:
        return None
    if len(cleaned) > _FILENAME_MAX_LEN:
        # Preserve extension if possible
        if "." in cleaned[-10:]:
            stem, dot, ext = cleaned.rpartition(".")
            keep = _FILENAME_MAX_LEN - len(dot) - len(ext)
            if keep > 0:
                cleaned = stem[:keep] + dot + ext
            else:
                cleaned = cleaned[:_FILENAME_MAX_LEN]
        else:
            cleaned = cleaned[:_FILENAME_MAX_LEN]
    return cleaned
