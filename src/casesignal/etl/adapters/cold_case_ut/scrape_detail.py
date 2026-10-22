"""Parse one Utah BCI cold-case detail page (WordPress-rendered).

Detail page URL pattern:
  https://bci.utah.gov/coldcases/<slug>/

BCI publishes fields via WordPress post-meta-key markup:
  <li><span class='post-meta-key'>label:</span> value</li>

Notable BCI quirks:
- "Ethnicity/Race" is a single compound label — value flows into `race`,
  with downstream ethnicity classifier (transform.py) splitting Hispanic/
  Latino/Latina out.
- "type" is the case-type indicator (values: unsolvedhomicide, missing,
  unidentified, closed). Per Phase 4.2 plan revision, BCI removes solved
  cases from publication; there is NO structured Case Status field.
- "Case #" is the source case number. "NCIC#" and "NamUs Case Number"
  are federal cross-references (Utah's NCIC is new in migration 0005).
- Victim name is in an <h2> inside <section id="divisionContent">,
  NOT in the site-level <h1> (which is the DPS site header).

Missing fields default to None. Unknown labels are logged at DEBUG.
Photos: any <img> tag with src under /wp-content/uploads/ within the page.
Narrative: the longest <p> in the case content area (heuristic).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from casesignal.etl.services.bs_helpers import attr_str

logger = logging.getLogger(__name__)


_CASE_TYPE_VALUES = frozenset(
    {
        "unsolvedhomicide",
        "missingpersons",
        "missing",
        "unidentified",
        "closed",
    }
)

# Matches "Contact <Agency Name> (<phone...>)" paragraphs (leading "the" optional).
# Phone formats seen in the wild:
#   "Contact the Salt Lake City Police (801) 799-3000"  — area code in parens, rest outside
#   "Contact Kane County Sheriff (435) 644-2349"        — same pattern
#   "Contact South Salt Lake PD (801-412-3600)"         — full number inside parens
#   "Contact Utah DPS (1-833-DPS-SAFE)"                 — alphanumeric, inside parens
#
# Strategy: split at the LAST '(' — everything before is the agency name (trimmed),
# everything from '(' onward is the phone token (trimmed, trailing ')' stripped).
_CONTACT_PARAGRAPH_RE = re.compile(
    r"^Contact\s+(?:the\s+)?(.+?)\s+(\([^(]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PhotoRef:
    n: int  # 1-indexed photo number within page
    url: str  # absolute URL
    alt_text: str | None


@dataclass(frozen=True)
class DetailContents:
    slug: str
    name: str
    case_type: str | None
    case_number: str | None
    date_of_crime: str | None
    date_last_seen: str | None
    date_body_found: str | None
    dob: str | None
    dod: str | None
    age: str | None
    gender: str | None
    race: str | None  # raw source value (incl. compound "Ethnicity/Race"); split downstream
    height: str | None
    weight: str | None
    eye_color: str | None
    hair_color: str | None
    identifying_marks: str | None
    aliases: str | None
    occupation: str | None
    tribal_affiliation: str | None
    city: str | None
    county: str | None
    agency_name: str | None
    agency_phone: str | None
    ncic_case_id: str | None
    namus_case_id: str | None
    narrative: str | None
    photos: list[PhotoRef] = field(default_factory=list)


# Map BCI label text (lowercase, trailing colon stripped, whitespace-collapsed)
# → DetailContents field name.
_LABEL_TO_FIELD: dict[str, str] = {
    "type": "case_type",
    "case type": "case_type",
    "case #": "case_number",
    "case number": "case_number",
    "date of crime": "date_of_crime",
    "date last seen": "date_last_seen",
    "date body found": "date_body_found",
    "date of birth": "dob",
    "dob": "dob",
    "date of death": "dod",
    "dod": "dod",
    "age": "age",
    "gender": "gender",
    "race": "race",
    "ethnicity": "race",
    "ethnicity/race": "race",
    "height": "height",
    "weight": "weight",
    "eye color": "eye_color",
    "eyes": "eye_color",
    "hair color": "hair_color",
    "hair": "hair_color",
    "identifying marks": "identifying_marks",
    "clothing": "identifying_marks",
    "aliases": "aliases",
    "occupation": "occupation",
    "tribal affiliation": "tribal_affiliation",
    "city": "city",
    "county": "county",
    "agency": "agency_name",
    "submitting agency": "agency_name",
    "investigating agency": "agency_name",
    "ncic": "ncic_case_id",
    "ncic#": "ncic_case_id",
    "ncic number": "ncic_case_id",
    "namus": "namus_case_id",
    "namus #": "namus_case_id",
    "namus case number": "namus_case_id",
}


def _label_value_pairs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Walk every <span class='post-meta-key'>label:</span> value."""
    pairs: list[tuple[str, str]] = []
    for span in soup.select("span.post-meta-key"):
        label_text = " ".join(span.get_text().split())  # "type:" / "Case #:" / "Date Last Seen:"
        label = label_text.rstrip(":").strip()
        if not label:
            continue
        # Value = parent text minus the leading label_text
        parent = span.parent
        if parent is None:
            continue
        full = " ".join(parent.get_text().split())
        # full looks like "type: unsolvedhomicide" or "Case #: 1998-110456"
        # Strip the leading label portion.
        if full.startswith(label_text):
            value = full[len(label_text) :].strip()
        elif full.startswith(label):
            value = full[len(label) :].lstrip(":").strip()
        else:
            # Conservative fallback
            value = full.replace(label_text, "", 1).strip()
        if value:
            pairs.append((label, value))
    return pairs


def parse_detail_page(html: str, *, slug: str) -> DetailContents:
    """Parse one Utah BCI detail page HTML into a DetailContents dataclass.

    Missing fields default to None. Unknown labels logged at DEBUG.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Initialize all labeled fields to None
    parsed: dict[str, str | None] = {f: None for f in set(_LABEL_TO_FIELD.values())}

    # Name from <h2> inside <section id="divisionContent">.
    # The site-level <h1> is the DPS site header, not the victim name.
    # The first <h2> inside divisionContent is the victim name.
    name = ""
    content_section = soup.find("section", id="divisionContent")
    if content_section:
        h2 = content_section.find("h2")
        if h2:
            name = " ".join(h2.get_text().split())
    if not name:
        # Fallback: any <h2> not inside a nav/header element
        for h2 in soup.find_all("h2"):
            # Skip h2 elements inside nav sections
            ancestors = {a.name for a in h2.parents}
            if "nav" not in ancestors and "header" not in ancestors:
                candidate = " ".join(h2.get_text().split())
                if candidate:
                    name = candidate
                    break

    # Label/value pairs
    for label, value in _label_value_pairs(soup):
        key = label.lower()
        field_name = _LABEL_TO_FIELD.get(key)
        if field_name is None:
            logger.debug("UT detail %s: unknown label %r", slug, label)
            continue
        # Only set if not already populated (defensive against duplicate labels)
        if parsed.get(field_name) is None:
            parsed[field_name] = value

    # Fallback: many BCI pages don't put Agency in post-meta-keys; they use
    # a free-form "Contact <Agency Name> (<phone>)" paragraph instead.
    # group(1) = agency name; group(2) = phone token starting with '(' (strip parens).
    fallback_phone: str | None = None
    if parsed.get("agency_name") is None:
        for p_tag in soup.find_all("p"):
            ptext = " ".join(p_tag.get_text().split())
            m = _CONTACT_PARAGRAPH_RE.match(ptext)
            if m:
                parsed["agency_name"] = m.group(1).strip().rstrip(".")
                raw_phone = m.group(2).strip()
                # Strip outer parens if present (e.g. "(801-412-3600)" → "801-412-3600")
                # For "(801) 799-3000" keep as-is since trailing ) belongs to area code only
                fallback_phone = raw_phone.lstrip("(").rstrip(")")
                break

    # Narrative — find the longest <p> on the page, with a minimum threshold
    narrative: str | None = None
    candidates = soup.find_all("p")
    if candidates:
        longest = max(candidates, key=lambda p: len(p.get_text()))
        text = " ".join(longest.get_text().split())
        if len(text) > 60:
            narrative = text

    # Photos: <img> tags with src under /wp-content/uploads/
    photos: list[PhotoRef] = []
    seen_urls: set[str] = set()
    for n, img in enumerate(
        (i for i in soup.find_all("img") if "/wp-content/uploads/" in (attr_str(i, "src") or "")),
        start=1,
    ):
        src = attr_str(img, "src") or ""
        if src in seen_urls:
            continue
        seen_urls.add(src)
        alt = attr_str(img, "alt") or None
        photos.append(PhotoRef(n=n, url=src, alt_text=alt))

    return DetailContents(
        slug=slug,
        name=name,
        narrative=narrative,
        photos=photos,
        agency_phone=fallback_phone,
        **parsed,
    )
