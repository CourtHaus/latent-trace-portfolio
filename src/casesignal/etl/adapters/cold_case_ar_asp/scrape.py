"""HTML parsing helpers for the Arkansas State Police CID cold-cases site.

Pure parsing logic — given fetched HTML, extract structured fields. No HTTP
here; the polite_http client lives one layer up in adapter.py / raw_load.

Verified site facts (2026-07-06) this module encodes:

- The index lists every case TWICE: once in the left sidebar menu
  (``ul`` with a ``sidebar-menu`` class) and once in center content lists
  (``ul.wp-block-list``). The two panes mirror each other, but 10 slugs are
  Capitalized in one pane and lowercase in the other; both casings serve the
  same page. We union both panes, dedupe on lowercased slug, and WARN (not
  fail) on any link found in only one pane — the panes drifting apart is a
  site-edit smell worth surfacing in QA.
- Detail pages carry a uniform field block of
  ``<p class="wp-block-paragraph"><strong>LABEL:</strong> value</p>`` rows
  (AGE / RACE / SEX / DATE OF DEATH | DATE MISSING / CAUSE / COUNTY /
  CASE NUMBER; every field optional — the multi-victim Testford page has no
  SEX), then narrative paragraphs, then a boilerplate contact paragraph
  distinguished by its ``is-style-info`` class.
- Case photos are ``media.ark.org`` images, lazy-loaded (real URL in
  ``srcset`` / ``data-lazy-src`` / a ``<noscript>`` twin). Site chrome
  (header banner, logos) also lives on media.ark.org and is excluded by
  filename denylist.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

INDEX_URL = (
    "https://dps.arkansas.gov/law-enforcement/arkansas-state-police"
    "/divisions/criminal-investigations/cold-cases/"
)

_DETAIL_HREF_RE = re.compile(
    r"/law-enforcement/arkansas-state-police/divisions/criminal-investigations"
    r"/cold-cases/(?P<slug>[^/?#]+)/?$"
)

# Known field labels on detail pages. Unknown labels are logged, not fatal.
KNOWN_LABELS = frozenset(
    {"AGE", "RACE", "SEX", "DATE OF DEATH", "DATE MISSING", "CAUSE", "COUNTY", "CASE NUMBER"}
)

# Chrome images that live on media.ark.org alongside real case photos.
_CHROME_IMAGE_RE = re.compile(r"(logo|COLD-CASES-web-header)", re.IGNORECASE)

_module_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexEntry:
    slug: str  # lowercased; the case-insensitive identity key
    url: str  # absolute detail URL (as linked; one URL per slug)
    link_text: str  # display name, e.g. "Ada Ann Exampleton Example"


@dataclass(frozen=True)
class ArPhoto:
    source_url: str
    alt: str | None
    filename_hint: str  # URL basename, e.g. "Robin-Sampleton-1.jpg"


@dataclass(frozen=True)
class ArDetailFields:
    """Parsed fields from a single detail page. Every field optional."""

    age_text: str | None
    race: str | None
    sex: str | None
    date_label: str | None  # 'death' | 'missing' | None
    date_text: str | None
    cause: str | None
    county: str | None
    case_number: str | None
    narrative: str  # prose paragraphs joined with blank lines; no contact para
    contact_text: str | None  # the full boilerplate contact paragraph
    contact_agency: str | None  # e.g. "ASP Company D"
    contact_phone: str | None  # e.g. "(479) 365-8710"
    photos: list[ArPhoto] = field(default_factory=list)


def _case_links(root: Tag, base_url: str) -> dict[str, tuple[str, str]]:
    """{lowercased_slug: (absolute_url, link_text)} for case links under root."""
    out: dict[str, tuple[str, str]] = {}
    for a in root.find_all("a", href=True):
        href = attr_str(a, "href")
        if href is None:
            continue
        m = _DETAIL_HREF_RE.search(href)
        if not m:
            continue
        slug = m.group("slug").lower()
        if slug in out:
            continue
        out[slug] = (urljoin(base_url, href), a.get_text(strip=True))
    return out


def parse_index_links(
    html: str,
    base_url: str,
    *,
    logger: logging.Logger | None = None,
) -> list[IndexEntry]:
    """Union case links from both index panes; dedupe on lowercased slug.

    Warns on any slug present in only one pane (site-edit drift signal).
    """
    log = logger or _module_logger
    soup = BeautifulSoup(html, "html.parser")

    sidebar_roots = soup.select("ul[class*='sidebar-menu']")
    content_roots = soup.select("ul.wp-block-list")

    sidebar: dict[str, tuple[str, str]] = {}
    for root in sidebar_roots:
        sidebar.update(_case_links(root, base_url))
    content: dict[str, tuple[str, str]] = {}
    for root in content_roots:
        content.update(_case_links(root, base_url))

    for slug in sorted(set(sidebar) ^ set(content)):
        pane = "sidebar" if slug in sidebar else "content"
        log.warning("AR ASP index: case %r found only in the %s pane", slug, pane)

    merged = {**sidebar, **content}  # content pane wins on URL casing; same page
    return [
        IndexEntry(slug=slug, url=url, link_text=text)
        for slug, (url, text) in sorted(merged.items())
    ]


_CONTACT_RE = re.compile(
    r"contact\s+(?P<agency>ASP[\w\s]+?)\s+at\s+(?P<phone>\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})"
)


def _photo_url(img: Tag) -> str | None:
    """Resolve the real image URL from a (possibly lazy-loaded) <img>."""
    for attr in ("src", "data-lazy-src"):
        v = attr_str(img, attr)
        if v and v.startswith("http"):
            return v
    for attr in ("srcset", "data-lazy-srcset"):
        v = attr_str(img, attr)
        if v:
            first = v.split(",")[0].strip().split(" ")[0].strip()
            if first.startswith("http"):
                return first
    return None


def _extract_photos(soup: BeautifulSoup) -> list[ArPhoto]:
    out: list[ArPhoto] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        url = _photo_url(img)
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.netloc != "media.ark.org":
            continue
        filename = parsed.path.rsplit("/", 1)[-1]
        if _CHROME_IMAGE_RE.search(filename):
            continue
        if url in seen:
            continue  # lazy-load noscript twin of the same image
        seen.add(url)
        alt = attr_str(img, "alt") or attr_str(img, "title") or None
        out.append(ArPhoto(source_url=url, alt=alt or None, filename_hint=filename))
    return out


def parse_detail_page(
    html: str,
    *,
    logger: logging.Logger | None = None,
) -> ArDetailFields:
    """Parse one AR ASP case detail page.

    Label rows are read as label → value pairs (not positional), every label
    optional. Unknown labels warn and continue: a novel label should surface
    in QA, not crash the run.
    """
    log = logger or _module_logger
    soup = BeautifulSoup(html, "html.parser")

    fields: dict[str, str] = {}
    narrative_parts: list[str] = []
    contact_text: str | None = None

    for p in soup.select("p.wp-block-paragraph"):
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        raw_classes: str | list[str] = p.get("class") or []
        classes = [raw_classes] if isinstance(raw_classes, str) else raw_classes
        if "is-style-info" in classes:
            contact_text = text
            continue
        strong = p.find("strong")
        strong_text = strong.get_text(" ", strip=True) if strong is not None else ""
        if strong is not None and strong_text.endswith(":") and text.startswith(strong_text):
            label = strong_text[:-1].strip().upper()
            if label in KNOWN_LABELS:
                fields[label] = text[len(strong_text):].strip()
                continue
            # Unknown bold-prefixed paragraph. These are prose, not structured
            # fields: an investigative "UPDATE:" note (e.g. a DNA/Othram lead),
            # an "Additional details can be found here:" link, or a plural
            # "AGES:" on multi-victim pages. Keep the FULL paragraph in the
            # narrative so the content reaches about_text and extraction — a
            # bare label whitelist would silently drop it. Still warn so a
            # genuinely-new structured field surfaces in QA.
            log.warning(
                "AR ASP detail: unknown bold label %r kept in narrative (value %r)",
                label,
                text[len(strong_text):].strip(),
            )
        narrative_parts.append(text)

    date_label: str | None = None
    date_text: str | None = None
    if "DATE OF DEATH" in fields:
        date_label, date_text = "death", fields["DATE OF DEATH"]
    elif "DATE MISSING" in fields:
        date_label, date_text = "missing", fields["DATE MISSING"]

    contact_agency: str | None = None
    contact_phone: str | None = None
    if contact_text:
        cm = _CONTACT_RE.search(contact_text)
        if cm:
            contact_agency = cm.group("agency").strip()
            contact_phone = cm.group("phone").strip()
        else:
            log.warning("AR ASP detail: contact paragraph didn't match: %r", contact_text[:120])

    return ArDetailFields(
        age_text=fields.get("AGE") or None,
        race=fields.get("RACE") or None,
        sex=fields.get("SEX") or None,
        date_label=date_label,
        date_text=date_text or None,
        cause=fields.get("CAUSE") or None,
        county=fields.get("COUNTY") or None,
        case_number=fields.get("CASE NUMBER") or None,
        narrative="\n\n".join(narrative_parts).strip(),
        contact_text=contact_text,
        contact_agency=contact_agency,
        contact_phone=contact_phone,
        photos=_extract_photos(soup),
    )
