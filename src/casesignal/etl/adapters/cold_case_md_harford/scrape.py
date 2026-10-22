"""HTML scraping for the Harford County Sheriff cold-cases page.

Single-page site with ~21 cases. Page structure:

    ul.subjects.type-1 > li > [
        div.img > img,
        div.info > h2 (victim name) + p+ (narrative)
    ]

Year is NOT in the h2 heading — it is extracted from the first
narrative paragraph (each case opens with a dated incident sentence).
Each li also has a duplicate of the first paragraph and a bare
date paragraph, which are deduplicated / filtered here.

source_case_id strategy: slug(case_name) + "-" + year extracted from
the first narrative paragraph, with collision disambiguation post-pass.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_FILENAME_MAX_LEN = 100

# Paragraphs that are tips/contact boilerplate — omit from narrative.
_SKIP_P_PREFIXES = (
    "call us at",
    "submit an anonymous tip",
    "anyone with information",
    "contact",
)


@dataclass(frozen=True)
class CaseSection:
    """One victim section parsed from the Harford index page."""

    case_name: str
    narrative_text: str
    source_case_id: str
    fallback_source_case_id: str
    photo_url: str | None
    photo_filename: str | None
    photo_alt_text: str | None


def parse_cold_case_sections(html: str, *, base_url: str) -> list[CaseSection]:
    """Walk ul.subjects > li items; emit one CaseSection per victim."""
    soup = BeautifulSoup(html, "html.parser")

    ul = soup.find("ul", class_="subjects")
    if ul is None:
        return []

    lis = ul.find_all("li", recursive=False)
    out: list[CaseSection] = []

    for li in lis:
        # Victim name from div.info > h2
        info_div = li.find("div", class_="info")
        if info_div is None:
            continue
        h2 = info_div.find("h2")
        if h2 is None:
            continue
        case_name = " ".join(h2.get_text().split()).strip()
        if not case_name or len(case_name) < 2:
            continue

        # Gather narrative paragraphs; deduplicate adjacent duplicate
        # paragraphs (Harford's CMS emits each first paragraph twice).
        raw_paragraphs: list[str] = []
        seen_texts: set[str] = set()
        for p in info_div.find_all("p"):
            text = " ".join(p.get_text().split()).strip()
            if not text:
                continue
            lower = text.lower()
            # Skip contact/tip boilerplate.
            if any(lower.startswith(prefix) for prefix in _SKIP_P_PREFIXES):
                continue
            # Skip bare date-only paragraphs (e.g. "March 21, 2015").
            if _is_bare_date(text):
                continue
            # Deduplicate: Harford CMS duplicates the first paragraph.
            if text in seen_texts:
                continue
            seen_texts.add(text)
            raw_paragraphs.append(text)

        narrative = " ".join(raw_paragraphs).strip()
        if len(narrative) < 50:
            continue

        # Extract year from narrative for source_case_id.
        year_match = _YEAR_RE.search(narrative)
        year_part = year_match.group(0) if year_match else None

        slug_base = _slugify(case_name)
        source_case_id = f"{slug_base}-{year_part}" if year_part else slug_base
        fallback_id = slug_base

        # Photo from sibling div.img > img
        img_div = li.find("div", class_="img")
        photo_url_abs: str | None = None
        photo_filename: str | None = None
        photo_alt: str | None = None
        if img_div is not None:
            img_tag = img_div.find("img")
            if isinstance(img_tag, Tag):
                raw_src = attr_str(img_tag, "src") or ""
                if raw_src:
                    photo_url_abs = urljoin(base_url, raw_src)
                    parsed = urlparse(photo_url_abs)
                    raw_fname = parsed.path.rsplit("/", 1)[-1]
                    photo_filename = sanitize_filename(raw_fname)
                photo_alt = attr_str(img_tag, "alt") or None

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

    # Disambiguate collisions: append -2, -3, ... per duplicate.
    counts = Counter(s.source_case_id for s in out)
    if any(c > 1 for c in counts.values()):
        seen_ids: dict[str, int] = {}
        deduped: list[CaseSection] = []
        for s in out:
            if counts[s.source_case_id] > 1:
                seen_ids[s.source_case_id] = seen_ids.get(s.source_case_id, 0) + 1
                if seen_ids[s.source_case_id] == 1:
                    deduped.append(s)
                else:
                    deduped.append(
                        replace(
                            s,
                            source_case_id=(f"{s.source_case_id}-{seen_ids[s.source_case_id]}"),
                        )
                    )
            else:
                deduped.append(s)
        out = deduped

    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BARE_DATE_RE = re.compile(
    r"^(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}$",
    re.IGNORECASE,
)


def _is_bare_date(text: str) -> bool:
    """Return True if text is solely a month-day-year date string."""
    return bool(_BARE_DATE_RE.match(text.strip()))


def _slugify(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s or "unknown"


def sanitize_filename(raw: str) -> str | None:
    """Strip unsafe characters; truncate to _FILENAME_MAX_LEN preserving
    the extension where possible.
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
