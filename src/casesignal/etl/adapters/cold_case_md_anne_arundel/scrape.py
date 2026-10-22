"""HTML scraping for the Anne Arundel County PD cold-cases page.

Single-page Drupal site: ~75 h3-anchored sections, each containing the
victim's name in the h3 and a narrative + photo nearby.

Page structure (verified against fixture 2026-05-08):

    <div class="row">
      <div class="col-md-3 ...">           # photo column
        <div class="round-corners">
          <img src="..." alt="...">
        </div>
      </div>
      <div class="col-md-9 col-xs-12">     # text column
        <h3>Victim Name</h3>
        <p>Case Number: 70-052500</p>
        <p>On October 7, 1970 ...narrative...</p>
        <p>Contact Homicide Unit ...</p>
      </div>
    </div>

For 2 sections (unknown victims), the case number appears in the h3
itself rather than the body — we pull it out with the same regex either
way.

Case number patterns observed: "Case Number: 70-052500", "Case Number:
72-037847" — uniform across the corpus.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str

_CASE_NUMBER_RE = re.compile(
    r"Case\s*(?:Number|#|No\.?)\s*:?\s*([A-Za-z0-9\-]+)",
    re.IGNORECASE,
)
_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")
_FILENAME_MAX_LEN = 100


@dataclass(frozen=True)
class CaseSection:
    """One victim section parsed from the AA index page.

    source_case_id is the police case number from the narrative when
    unique within the page; for multi-victim incidents (e.g., shared
    case number 06-716897 for two co-killed victims), it's suffixed
    with the victim slug to preserve uniqueness on
    cold_case.cases (dataset_version_id, source_case_id).
    """

    case_name: str  # h3 text (or "Unknown" for sections where the h3
    # is itself the case number)
    narrative_text: str  # joined paragraph(s), Case Number + Contact line
    # excluded
    source_case_id: str  # case number from narrative or h3, OR slugged
    # case_name fallback
    fallback_source_case_id: str  # always the slugged case_name (for
    # tests / debugging)
    photo_url: str | None  # absolute URL to first <img> in the section
    photo_filename: str | None  # sanitized filename
    photo_alt_text: str | None


def parse_cold_case_sections(html: str, *, base_url: str) -> list[CaseSection]:
    """Walk the page; emit one CaseSection per h3 victim block.

    Sections are matched by walking each h3, collecting <p> siblings
    until the next h3 (the narrative), and navigating up to the
    surrounding `.row` to find the sibling photo column.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[CaseSection] = []

    for h3 in soup.find_all("h3"):
        h3_text = " ".join(h3.get_text().split()).strip()
        if not h3_text or len(h3_text) < 4:
            continue
        # Skip non-victim h3s (page nav, reward sections, etc.)
        if "reward" in h3_text.lower() or "anyone with information" in h3_text.lower():
            continue

        # Walk forward through <p> siblings until next h3 to assemble
        # the narrative. Drop the "Case Number: ..." line (we extract
        # it separately) and the "Contact Homicide Unit" tail line.
        case_number_from_body: str | None = None
        narrative_parts: list[str] = []
        node = h3.next_sibling
        while node is not None:
            if isinstance(node, Tag):
                if node.name == "h3":
                    break
                if node.name == "p":
                    text = " ".join(node.get_text().split())
                    if not text:
                        node = node.next_sibling
                        continue
                    m = _CASE_NUMBER_RE.search(text)
                    if m and case_number_from_body is None:
                        case_number_from_body = m.group(1)
                        # If the paragraph is JUST the case number line
                        # (typical), don't include it in narrative.
                        if _CASE_NUMBER_RE.sub("", text).strip().strip(":-").strip() == "":
                            node = node.next_sibling
                            continue
                    lower = text.lower()
                    # Skip non-narrative call-to-action paragraphs:
                    # "Contact Homicide Unit ..." / "Anyone with
                    # information ..." (contact instructions),
                    # "Watch ... Story" (video CTAs).
                    if lower.startswith("contact homicide unit"):
                        node = node.next_sibling
                        continue
                    if lower.startswith("anyone with information"):
                        node = node.next_sibling
                        continue
                    if lower.startswith("watch ") and "story" in lower:
                        node = node.next_sibling
                        continue
                    narrative_parts.append(text)
            node = node.next_sibling

        narrative = " ".join(narrative_parts).strip()
        if len(narrative) < 50:
            # Not a real victim section (could be a page-nav h3 etc.)
            continue

        # Case-name vs case-number handling: if the h3 text itself is
        # a "Case Number: X" line, the victim is unknown — strip it
        # for the case_name and use the embedded number as the id.
        case_name = h3_text
        m_h3 = _CASE_NUMBER_RE.match(h3_text)
        if m_h3 and case_number_from_body is None:
            case_number_from_body = m_h3.group(1)
            case_name = "Unknown"

        fallback_id = _slugify(h3_text)
        source_case_id = case_number_from_body or fallback_id

        # Find the sibling photo column via the .row ancestor.
        photo_url: str | None = None
        photo_alt: str | None = None
        col9 = h3.find_parent("div", class_="col-md-9")
        if col9 is not None:
            row = col9.find_parent("div", class_="row")
            if row is not None:
                col3 = row.find("div", class_="col-md-3")
                if col3 is not None:
                    img = col3.find("img")
                    if img is not None:
                        photo_url = attr_str(img, "src")
                        photo_alt = attr_str(img, "alt") or None

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

    # Disambiguate source_case_ids that collide (multi-victim incidents
    # share a police case number; we model each victim as its own case).
    counts = Counter(s.source_case_id for s in out)
    if any(c > 1 for c in counts.values()):
        deduped: list[CaseSection] = []
        for s in out:
            if counts[s.source_case_id] > 1:
                victim_slug = _slugify(s.case_name)
                deduped.append(
                    replace(
                        s,
                        source_case_id=f"{s.source_case_id}-{victim_slug}",
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
