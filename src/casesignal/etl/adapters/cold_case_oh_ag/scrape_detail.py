"""Parse one OH AG cold-case detail page.

The page uses semantic <h2> headings (Unsolved Homicides, Details,
Contact, Additional pictures) and renders fields as:
  <li><strong>Label:</strong> value</li>
or (for case number) as:
  <li><strong>Case number: 1884</strong></li>

City and county are embedded within the Incident location <li> text
(multi-line with <br/>), not as separate fields.  They are parsed
out of the location text via pattern matching.

Photos: every <img> whose src contains "/getattachment/" is collected.
The first such image is marked is_primary.

Dates published as M/D/YYYY are normalized to ISO 8601 YYYY-MM-DD.
Weight published as "NNN lbs" or "NNN" is parsed to int.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str


@dataclass(frozen=True)
class PhotoRef:
    """Reference to an image on the detail page; resolved to URL by raw_load."""

    src: str
    alt: str | None
    is_primary: bool


@dataclass(frozen=True)
class DetailContents:
    """Parsed detail-page content. Every field is Optional; missing → None."""

    case_number: str | None
    name: str | None
    aliases: str | None
    dob: str | None
    gender: str | None
    race: str | None
    height: str | None
    weight_lbs: int | None
    hair_color: str | None
    eye_color: str | None
    incident_date: str | None
    address: str | None
    city: str | None
    county: str | None
    agency: str | None
    narrative: str | None
    photos: list[PhotoRef] = field(default_factory=list)


_DATE_SLASH_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")

# Section headings to skip when searching for the victim name.
_SECTION_HEADINGS_LC = frozenset(
    {
        "unsolved homicides",
        "details",
        "contact",
        "additional pictures",
    }
)

# Suffix patterns appended to the victim name in the <h2> element.
_NAME_SUFFIX_RE = re.compile(
    r"\s+(unsolved\s+homicide|solved\s+homicide|homicide)\s*$",
    re.IGNORECASE,
)

# Location field patterns — applied line-by-line, not against the full text.
# City line:    "Oakwood,"   or   "Oakwood, "
_CITY_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z '-]+?),?\s*$")
# County line:  "- Paulding County"
_COUNTY_LINE_RE = re.compile(r"^-\s*([A-Za-z][A-Za-z\s]+County)\s*$", re.IGNORECASE)


def _normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    m = _DATE_SLASH_RE.match(raw.strip())
    if not m:
        return None
    mo, da, yr = (int(g) for g in m.groups())
    try:
        return datetime(yr, mo, da).date().isoformat()
    except ValueError:
        return None


def _parse_weight(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"(\d+)", raw)
    return int(m.group(1)) if m else None


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v or None


def _li_label_value(li: Tag) -> tuple[str, str] | None:
    """Extract (lowercased_label, value) from an <li> containing a bold label.

    Handles both:
      <li><strong>Label:</strong> value text</li>
      <li><b>Label:</b> value text</li>
      <li><strong>Label: value (all bold)</strong></li>
    """
    bold = li.find(["strong", "b"])
    if not bold:
        return None

    bold_text = (bold.get_text() or "").strip()

    if ":" not in bold_text:
        return None

    colon_pos = bold_text.index(":")
    label = bold_text[:colon_pos].strip().lower()
    value_in_bold = bold_text[colon_pos + 1 :].strip()

    if value_in_bold:
        # Value embedded inside the bold tag (e.g. "Case number: 1884")
        return label, value_in_bold
    else:
        # Value is the text that follows the bold element in the <li>
        # Collect all text nodes after the bold tag
        remaining = []
        for node in bold.next_siblings:
            if hasattr(node, "get_text"):
                remaining.append(node.get_text())
            else:
                remaining.append(str(node))
        value = " ".join(remaining).strip()
        # Remove a leading colon that may appear in the sibling text
        value = re.sub(r"^:\s*", "", value).strip()
        if not value:
            return None
        return label, value


def _extract_location_parts(
    raw_li_text: str,
) -> tuple[str | None, str | None, str | None]:
    """Parse address, city, county out of the raw incident-location <li> text.

    The AG page serialises the location as multi-line HTML inside one <li>
    (the tag is not closed before the next <li>, so BS4 nests everything
    below it).  After stripping the label prefix, the first non-empty line
    is the street address.  We then scan subsequent lines for:
      - "CityName,"  → city
      - "- Foo County" → county
    We stop scanning as soon as we encounter a line that looks like another
    field label (contains a colon followed by a date/value), to avoid
    false-positives from nested <li> content.
    """
    lines = [ln.strip() for ln in raw_li_text.split("\n") if ln.strip()]

    address: str | None = lines[0] if lines else None
    city: str | None = None
    county: str | None = None

    # Only scan the first several lines — after "- County" we're done with
    # the location block; later lines belong to subsequent fields.
    for line in lines[1:]:
        # Stop if this looks like another field (label: value)
        if re.search(r"^[A-Za-z][A-Za-z ]+:\s", line):
            break
        if city is None:
            m = _CITY_LINE_RE.match(line)
            if m:
                city = m.group(1).strip()
                continue
        if county is None:
            m = _COUNTY_LINE_RE.match(line)
            if m:
                county = m.group(1).strip()
                continue

    return address, city, county


def parse_detail(html: str, *, source_url: str) -> DetailContents:
    """Parse a single detail page into DetailContents."""
    soup = BeautifulSoup(html, "html.parser")

    # --- Victim name ---
    # First <h2> that is NOT a known section heading, with suffix stripped.
    name: str | None = None
    for h in soup.find_all("h2"):
        raw = (h.get_text() or "").strip()
        # Collapse non-breaking spaces
        raw = raw.replace(" ", " ").strip()
        if not raw:
            continue
        if raw.lower() in _SECTION_HEADINGS_LC:
            continue
        # Strip trailing "Unsolved homicide" etc.
        cleaned = _NAME_SUFFIX_RE.sub("", raw).strip()
        if cleaned:
            name = cleaned
            break

    # --- Field extraction from <li> elements ---
    fields: dict[str, str] = {}
    location_li_text: str | None = None

    for li in soup.find_all("li"):
        kv = _li_label_value(li)
        if not kv:
            continue
        label, value = kv
        # First occurrence wins for most fields
        if label not in fields:
            fields[label] = value
        # Capture the raw multi-line text for the incident location field
        # so we can parse address/city/county out of it.
        if label == "incident location" and location_li_text is None:
            location_li_text = li.get_text(separator="\n")

    # --- Address / city / county ---
    address: str | None = None
    city: str | None = None
    county: str | None = None

    if location_li_text:
        # Strip the label prefix ("Incident location:") from the li text.
        loc_body = re.sub(
            r"^incident\s+location\s*:\s*",
            "",
            location_li_text.strip(),
            flags=re.IGNORECASE,
        )
        address, city, county = _extract_location_parts(loc_body)
    else:
        # Fallback: separate city/county fields (not present in AG pages but
        # keeps minimal-HTML test working).
        address = _strip(fields.get("incident location") or fields.get("location"))
        city = _strip(fields.get("city") or fields.get("town"))
        county = _strip(fields.get("county"))

    # --- Narrative ---
    # Paragraph immediately following the <h2>Details</h2> heading.
    narrative: str | None = None
    for h2 in soup.find_all("h2"):
        if (h2.get_text() or "").strip().lower() == "details":
            # Walk siblings until we find a <p>
            for sibling in h2.next_siblings:
                if not isinstance(sibling, Tag):
                    continue
                if sibling.name == "p":
                    t = sibling.get_text().strip()
                    if t:
                        narrative = t
                    break
                # Stop if we hit another heading
                if sibling.name in ("h1", "h2", "h3"):
                    break
            break

    # --- Photos ---
    # Collect <img> whose src contains "/getattachment/" — the AG CMS pattern
    # for user-uploaded assets.  Skip site chrome (watermark, social icons,
    # nav icons, search widget).
    photos: list[PhotoRef] = []
    primary_assigned = False
    for img in soup.find_all("img"):
        src = (attr_str(img, "src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        if "/getattachment/" not in src:
            continue
        alt = _strip(attr_str(img, "alt"))
        photos.append(
            PhotoRef(
                src=src,
                alt=alt,
                is_primary=not primary_assigned,
            )
        )
        primary_assigned = True

    # --- Resolve aliases ---
    aliases = _strip(
        fields.get("nickname or alias")
        or fields.get("alias")
        or fields.get("aliases")
        or fields.get("nickname")
        or fields.get("alias/nickname")
    )

    # --- Resolve race (Race/Ethnicity label on AG pages) ---
    race = _strip(fields.get("race/ethnicity") or fields.get("race") or fields.get("ethnicity"))

    # --- Resolve agency ---
    agency = _strip(
        fields.get("law enforcement agency")
        or fields.get("agency")
        or fields.get("investigating agency")
    )

    # --- Resolve incident date (prefer "incident date"; fallback "homicide date") ---
    incident_date = _normalize_date(fields.get("incident date") or fields.get("homicide date"))

    return DetailContents(
        case_number=_strip(fields.get("case number")),
        name=name,
        aliases=aliases,
        dob=_normalize_date(fields.get("date of birth")),
        gender=_strip(fields.get("gender") or fields.get("sex")),
        race=race,
        height=_strip(fields.get("height")),
        weight_lbs=_parse_weight(fields.get("weight")),
        hair_color=_strip(fields.get("hair color") or fields.get("hair")),
        eye_color=_strip(fields.get("eye color") or fields.get("eyes")),
        incident_date=incident_date,
        address=address,
        city=city,
        county=county,
        agency=agency,
        narrative=narrative,
        photos=photos,
    )
