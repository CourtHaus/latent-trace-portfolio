"""Parse one CO CBI case detail page.

Detail page structure:
  - Case-detail fields are <p>Label: <span>Value</span></p> inside div.floatLeft
  - Multiple photos are <img src="/coldcase/casefiles/{id}/{n}/large"> inside
    div.caseHolderPerson elements
  - Narrative is <p class="long">
  - Victim name is <div class="caseDetails"><div class="left"><h2>{name}</h2></div></div>
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from casesignal.etl.services.bs_helpers import attr_str

logger = logging.getLogger(__name__)


_PHOTO_URL_RE = re.compile(r"/coldcase/casefiles/(\d+)/(\d+)/large")


@dataclass(frozen=True)
class PhotoRef:
    n: int  # 1-indexed photo number
    url: str  # absolute URL
    alt_text: str | None


@dataclass(frozen=True)
class DetailContents:
    name: str
    aliases: str | None
    dob: str | None
    dod: str | None
    occupation: str | None
    age: str | None
    gender: str | None  # "Male" / "Female" / "" → None
    race: str | None
    ethnicity: str | None
    tribal_affiliation: str | None
    height: str | None
    weight: str | None
    eye_color: str | None
    hair_color: str | None
    identifying_marks: str | None
    case_type: str | None  # "Homicide" / "Missing" / etc.
    case_status: str | None  # "OPEN" / "SOLVED" / etc.
    incident_date: str | None
    agency: str | None
    agency_case_id: str | None
    judicial_district: str | None
    city: str | None
    county: str | None
    namus_case_id: str | None
    ncmec_case_id: str | None
    narrative: str | None
    photos: list[PhotoRef] = field(default_factory=list)


# Map detail-page labels → DetailContents field names
_LABEL_TO_FIELD: dict[str, str] = {
    "Case Type": "case_type",
    "Height": "height",
    "Case Status": "case_status",
    "Weight": "weight",
    "Aliases": "aliases",
    "Identifying Marks": "identifying_marks",
    "Incident Date": "incident_date",
    "Occupation": "occupation",
    "Agency": "agency",
    "City": "city",
    "Date of Birth": "dob",
    "County": "county",
    "Date of Death": "dod",
    "Agency Case #": "agency_case_id",
    "Judicial District": "judicial_district",
    "Age": "age",
    "Gender": "gender",
    "Race": "race",
    "Tribal Affiliation": "tribal_affiliation",
    "Ethnicity": "ethnicity",
    "NamUs Case #": "namus_case_id",
    "Eye Color": "eye_color",
    "NCMEC Case #": "ncmec_case_id",
    "Hair Color": "hair_color",
}


_LABEL_VALUE_RE = re.compile(r"^([^:]+):\s*(.*)$")


def parse_detail_page(html: str, *, detail_id: int, base_url: str) -> DetailContents:
    """Parse one detail page into a DetailContents dataclass."""
    soup = BeautifulSoup(html, "html.parser")

    # Initialize labeled fields to None
    parsed: dict[str, str | None] = {f: None for f in _LABEL_TO_FIELD.values()}

    # Name
    name_el = soup.select_one("div.caseDetails div.left h2")
    name = " ".join(name_el.get_text().split()) if name_el else ""

    # Label/value pairs from <p>Label: <span>Value</span></p>
    for p in soup.select("div.floatLeft p"):
        text = " ".join(p.get_text().split())
        m = _LABEL_VALUE_RE.match(text)
        if not m:
            continue
        label = m.group(1).strip()
        value = m.group(2).strip()
        field_name = _LABEL_TO_FIELD.get(label)
        if field_name is None:
            continue
        parsed[field_name] = value if value else None

    # Narrative
    narrative_el = soup.select_one("p.long")
    narrative: str | None = None
    if narrative_el:
        narrative_text = narrative_el.get_text().strip()
        narrative = narrative_text if narrative_text else None

    # Photos
    photos: list[PhotoRef] = []
    for img in soup.select("div.caseHolderPerson img"):
        src = attr_str(img, "src") or ""
        m = _PHOTO_URL_RE.search(src)
        if not m:
            continue
        n = int(m.group(2))
        absolute = urljoin(base_url, src)
        alt = attr_str(img, "alt") or None
        photos.append(PhotoRef(n=n, url=absolute, alt_text=alt))

    return DetailContents(
        name=name,
        narrative=narrative,
        photos=photos,
        **parsed,
    )
