"""HTML scraping for the Howard County PD cold-cases page.

Single-page Drupal site with ~26 accordion sections (23 unsolved + 3
SOLVED). The DOM structure per case is:

    <article class="accordion-item ...">
      <h3 class="accordion-item__heading">Homicide of <Name>, <date></h3>
      <div class="accordion-item__panel ...">
        <div class="... field--name-repeat-content ...">
          <article>...</article>   # Drupal media figure (wraps <img>)
          <p>...narrative...</p>
          <p>...narrative continued...</p>
        </div>
        ...
      </div>
    </article>

SOLVED/IDENTIFIED cases are prefixed `SOLVED:` or `IDENTIFIED:` in the
h3 text — we filter them out (out of scope for our cold-case dataset).

source_case_id strategy: slug(case_name) + "-" + year extracted from
the heading date string, with collision disambiguation post-pass.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

_HOMICIDE_PREFIX_RE = re.compile(r"^homicide of\s+", re.IGNORECASE)
# Only SOLVED cases are filtered; IDENTIFIED cases are victim-named but
# still unsolved (active investigations). Strip IDENTIFIED: prefix first.
_SOLVED_PREFIX_RE = re.compile(r"^solved\b", re.IGNORECASE)
_IDENTIFIED_PREFIX_RE = re.compile(r"^identified\s*:\s*", re.IGNORECASE)
_YEAR_IN_DATE_RE = re.compile(r"\b(19|20)\d{2}\b")
_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_FILENAME_MAX_LEN = 100


@dataclass(frozen=True)
class CaseSection:
    """One victim section parsed from the Howard index page.

    source_case_id = slug(case_name)-{year}, with disambiguation suffix
    (`-2`, `-3`) appended on collision. The fallback_source_case_id is
    the slug-without-year for tests / debugging.
    """

    case_name: str
    narrative_text: str
    source_case_id: str
    fallback_source_case_id: str
    photo_url: str | None
    photo_filename: str | None
    photo_alt_text: str | None


def parse_cold_case_sections(html: str, *, base_url: str) -> list[CaseSection]:
    """Walk the page; emit one CaseSection per unsolved victim block.

    Filters out:
    - SOLVED cases (prefix ``SOLVED:``) — case is closed.
    - Sections whose narrative content is too short to be useful.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[CaseSection] = []

    # Howard uses Drupal accordion: each case lives in an <article> with
    # class "accordion-item".  The heading is an <h3> inside it; the
    # narrative and photo are inside div.accordion-item__panel.
    accordion_items = soup.find_all("article", class_="accordion-item")

    for article in accordion_items:
        header = article.find("h3")
        if header is None:
            continue

        h_text = " ".join(header.get_text().split()).strip()
        if not h_text or len(h_text) < 4:
            continue

        # Filter SOLVED cases — out of scope.
        if _SOLVED_PREFIX_RE.match(h_text):
            continue

        # Strip IDENTIFIED: prefix (victim ID resolved, case still unsolved).
        h_text = _IDENTIFIED_PREFIX_RE.sub("", h_text, count=1).strip()

        # Keep only "Homicide of ..." sections; skip nav/misc accordion items.
        if not _HOMICIDE_PREFIX_RE.match(h_text):
            continue

        # Strip "Homicide of " prefix; split on first comma → name + date.
        body = _HOMICIDE_PREFIX_RE.sub("", h_text, count=1).strip()
        if "," in body:
            name_part, date_part = body.split(",", 1)
            case_name = name_part.strip()
            date_string = date_part.strip()
        else:
            case_name = body.strip()
            date_string = ""

        # Find the content panel, then the repeat-content field div inside it.
        panel = article.find("div", class_="accordion-item__panel")
        if panel is None:
            continue

        content_div = panel.find(
            "div",
            class_=lambda c: c is not None and "field--name-repeat-content" in c,
        )
        if content_div is None:
            content_div = panel

        # Collect narrative paragraphs and the first photo.
        narrative_parts: list[str] = []
        photo_url: str | None = None
        photo_alt: str | None = None

        for child in content_div.children:
            if not isinstance(child, Tag):
                continue

            # Drupal wraps images in <article class="...media..."> or <figure>.
            if child.name in ("article", "figure"):
                if photo_url is None:
                    img = child.find("img")
                    if isinstance(img, Tag):
                        photo_url = attr_str(img, "src")
                        photo_alt = attr_str(img, "alt") or None
                continue

            if child.name == "img" and photo_url is None:
                photo_url = attr_str(child, "src")
                photo_alt = attr_str(child, "alt") or None
                continue

            if child.name == "p":
                text = " ".join(child.get_text().split())
                if not text:
                    continue
                lower = text.lower()
                # Skip boilerplate call-to-action lines.
                if lower.startswith("anyone with information"):
                    continue
                if lower.startswith("contact"):
                    continue
                narrative_parts.append(text)

        narrative = " ".join(narrative_parts).strip()
        if len(narrative) < 50:
            continue

        # Build source_case_id = slug(case_name)-year.
        year_match = _YEAR_IN_DATE_RE.search(date_string)
        year_part = year_match.group(0) if year_match else None
        slug_base = _slugify(case_name)
        if year_part:
            source_case_id = f"{slug_base}-{year_part}"
        else:
            source_case_id = slug_base
        fallback_id = slug_base

        # Resolve absolute photo URL and sanitize filename.
        photo_url_abs: str | None = None
        photo_filename: str | None = None
        if photo_url:
            photo_url_abs = urljoin(base_url, photo_url)
            parsed = urlparse(photo_url_abs)
            raw = parsed.path.rsplit("/", 1)[-1]
            photo_filename = sanitize_filename(raw)

        out.append(
            CaseSection(
                case_name=case_name,
                narrative_text=narrative,
                source_case_id=source_case_id,
                fallback_source_case_id=fallback_id,
                photo_url=photo_url_abs,
                photo_filename=photo_filename,
                photo_alt_text=photo_alt,
            )
        )

    # Disambiguate collisions: append `-2`, `-3`, ... per duplicate.
    counts = Counter(s.source_case_id for s in out)
    if any(c > 1 for c in counts.values()):
        seen: dict[str, int] = {}
        deduped: list[CaseSection] = []
        for s in out:
            if counts[s.source_case_id] > 1:
                seen[s.source_case_id] = seen.get(s.source_case_id, 0) + 1
                if seen[s.source_case_id] == 1:
                    # First occurrence keeps the original id.
                    deduped.append(s)
                else:
                    deduped.append(
                        replace(
                            s,
                            source_case_id=(f"{s.source_case_id}-{seen[s.source_case_id]}"),
                        )
                    )
            else:
                deduped.append(s)
        out = deduped

    return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s or "unknown"


def sanitize_filename(raw: str) -> str | None:
    """Strip path separators / leading dots / null bytes;
    truncate to _FILENAME_MAX_LEN preserving extension where possible.
    """
    if not raw:
        return None
    cleaned = _FILENAME_SANITIZE_RE.sub("_", raw)
    cleaned = cleaned.lstrip(".")
    cleaned = cleaned.replace("\x00", "")
    if not cleaned:
        return None
    if len(cleaned) > _FILENAME_MAX_LEN:
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
