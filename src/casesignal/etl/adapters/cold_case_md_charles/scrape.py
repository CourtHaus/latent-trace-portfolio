"""HTML scraping for the Charles County Sheriff cold-cases page.

Index page (https://www.ccso.us/crime/cold-cases/) groups cases under
two H4 sections: 'Homicides' and 'Sexual Assaults'. We ingest only the
Homicides section. ARREST MADE entries are filtered out (solved).

Detail pages live at /crime/cold-cases/<slug>/ and contain the narrative.

source_case_id strategy: the URL slug, which is already case-stable
(e.g. 'cold-case-vickie-belk', 'deborah-ann-brooks').

NOTE ON STRUCTURE: The live page uses <h4> (not <h2>) for section headings.
Both _find_section_heading and _siblings_until_next_section_heading handle h4.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

_HOMICIDES_HEADING_RE = re.compile(r"^\s*homicides\s*$", re.IGNORECASE)
_ARREST_MADE_RE = re.compile(r"\bARREST\s+MADE\b", re.IGNORECASE)
_CASE_CLOSED_RE = re.compile(r"\bCASE\s+CLOSED\b", re.IGNORECASE)
_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_FILENAME_MAX_LEN = 100

# Heading tags used for section breaks (same level the site uses for sections)
_SECTION_HEADING_TAGS = ("h2", "h3", "h4")


class SourceStructureChangedError(RuntimeError):
    """Raised when the upstream page structure no longer matches expectations."""


@dataclass(frozen=True)
class CaseRef:
    """Index-level reference to one Charles County case detail page."""

    case_name: str
    detail_url: str
    source_case_id: str  # the URL slug


def parse_index(html: str, *, base_url: str) -> list[CaseRef]:
    """Parse the Charles County cold-cases index, homicides section only.

    Fail-closed: raises SourceStructureChangedError if the 'Homicides' heading
    cannot be located. Filters cases whose link text or surrounding span
    includes 'ARREST MADE' or 'CASE CLOSED'.
    """
    soup = BeautifulSoup(html, "html.parser")
    homicides_heading = _find_section_heading(soup, _HOMICIDES_HEADING_RE)
    if homicides_heading is None:
        raise SourceStructureChangedError(
            "Charles index: 'Homicides' heading not found. Site structure may have changed."
        )

    refs: list[CaseRef] = []
    for elem in _siblings_until_next_section_heading(homicides_heading):
        for a in _iter_case_links(elem):
            link_text = " ".join(a.get_text().split()).strip()
            if not link_text:
                continue
            surrounding = _surrounding_text(a)
            if _ARREST_MADE_RE.search(surrounding) or _CASE_CLOSED_RE.search(surrounding):
                continue
            href = (attr_str(a, "href") or "").strip()
            if not href:
                continue
            detail_url = urljoin(base_url, href)
            slug = _slug_from_url(detail_url)
            if not slug:
                continue
            refs.append(
                CaseRef(
                    case_name=_clean_case_name(link_text),
                    detail_url=detail_url,
                    source_case_id=slug,
                )
            )
    return _dedupe_by_slug(refs)


def _find_section_heading(soup: BeautifulSoup, label_re: re.Pattern[str]) -> Tag | None:
    """Find any h2/h3/h4 whose text matches label_re."""
    for h in soup.find_all(_SECTION_HEADING_TAGS):
        text = " ".join(h.get_text().split())
        if label_re.match(text):
            return h
    return None


def _siblings_until_next_section_heading(start: Tag) -> Iterator[Tag]:
    """Yield siblings of `start` until the next section heading (h2/h3/h4)."""
    for sib in start.next_siblings:
        if isinstance(sib, Tag) and sib.name in _SECTION_HEADING_TAGS:
            return
        if isinstance(sib, Tag):
            yield sib


def _iter_case_links(scope: Tag) -> Iterator[Tag]:
    """Yield <a> tags inside `scope` whose href looks like a detail page."""
    for a in scope.find_all("a", href=True):
        href = attr_str(a, "href")
        if href and "/crime/cold-cases/" in href and not href.rstrip("/").endswith("cold-cases"):
            yield a


def _surrounding_text(a: Tag) -> str:
    """Return text of the link's nearest block ancestor (li, div, p, h*),
    so 'ARREST MADE' shown as a sibling badge is detected."""
    for ancestor in a.parents:
        if ancestor.name in ("li", "div", "p", "h2", "h3", "h4"):
            return " ".join(ancestor.get_text().split())
        if ancestor.name == "body":
            break
    return a.get_text()


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if "/" in path else ""


def _clean_case_name(text: str) -> str:
    """Strip date-in-parens and status annotations from link text.

    Examples:
      'Deborah Ann Brooks (11/13/1980)' -> 'Deborah Ann Brooks'
      'Karen Sabrina Wills' -> 'Karen Sabrina Wills'
    """
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    text = re.sub(
        r"\s*[-–—]\s*(ARREST MADE|CASE CLOSED|IDENTIFIED.*)$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text


def _dedupe_by_slug(refs: list[CaseRef]) -> list[CaseRef]:
    seen: set[str] = set()
    out: list[CaseRef] = []
    for r in refs:
        if r.source_case_id in seen:
            continue
        seen.add(r.source_case_id)
        out.append(r)
    return out


@dataclass(frozen=True)
class CaseDetail:
    """Per-case detail-page parse result."""

    narrative_text: str
    photo_url: str | None
    photo_filename: str | None
    photo_alt_text: str | None


def parse_detail(html: str, *, case_ref_url: str) -> CaseDetail:
    """Parse a Charles County cold-case detail page.

    Strategy: pick the main content area (post body), join visible <p>
    text, take the first image as the primary photo. Filters tip-line
    boilerplate paragraphs.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=lambda c: c and "entry-content" in c)
        or soup
    )

    narrative_parts: list[str] = []
    for p in main.find_all("p"):
        text = " ".join(p.get_text().split()).strip()
        if not text:
            continue
        lower = text.lower()
        if lower.startswith(("anyone with information", "contact", "if you have")):
            continue
        if "crime stoppers" in lower or "tip line" in lower:
            continue
        narrative_parts.append(text)
    narrative = " ".join(narrative_parts).strip()

    photo_url: str | None = None
    photo_filename: str | None = None
    photo_alt: str | None = None
    img = main.find("img")
    if isinstance(img, Tag):
        src = (attr_str(img, "src") or "").strip()
        if src:
            photo_url = urljoin(case_ref_url, src)
            raw_name = urlparse(photo_url).path.rsplit("/", 1)[-1]
            photo_filename = sanitize_filename(raw_name)
            photo_alt = attr_str(img, "alt") or None

    return CaseDetail(
        narrative_text=narrative,
        photo_url=photo_url,
        photo_filename=photo_filename,
        photo_alt_text=photo_alt,
    )


def sanitize_filename(raw: str) -> str | None:
    """Same shape as Howard's helper — strip path separators / dots."""
    if not raw:
        return None
    cleaned = _FILENAME_SANITIZE_RE.sub("_", raw)
    cleaned = cleaned.lstrip(".").replace("\x00", "")
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
