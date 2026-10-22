"""Reader for the MN BCA browser-harvested JSON dump.

The case list sits behind an Imperva WAF; it is harvested out-of-band via
a browser console fetch against the SharePoint REST API (see the design
doc's "Harvest contract"). This module parses + validates that dump.

No case-number field exists in the source list, so source_case_id is
synthesized from name + incident date: `mn-{last}-{first}-{YYYY-MM-DD}`.
Uniqueness is enforced at parse time — parse_harvest raises HarvestError on a collision.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from casesignal.etl.services.normalizers import normalize_date

# Only the Unsolved Homicide subset is in scope.
_IN_SCOPE_CONTENT_TYPE = "Unsolved Homicide"
# Fields every in-scope record must carry for the adapter to function.
_REQUIRED_FIELDS = ("NameFirst", "NameLast", "Date1", "PDF")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class HarvestError(Exception):
    """Raised when the harvest file is empty, malformed, or inconsistent."""


@dataclass(frozen=True)
class HarvestRecord:
    """One in-scope (Unsolved Homicide) record from the BCA harvest."""
    source_case_id: str
    name_first: str
    name_middle: str | None
    name_last: str
    name_suffix: str | None
    age: str | None  # source Age is int; stored as str — downstream treats age as text
    incident_date_raw: str  # Date1, as harvested (M/D/YYYY)
    incident_date_iso: str | None  # normalized YYYY-MM-DD
    date_of_birth: str | None
    location_city: str | None
    location_county: str | None
    location_state: str | None
    pdf_path: str  # relative path from the PDF field
    picture_path: str | None  # relative path from Picture1
    reward: int | None


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.strip().lower()).strip("-")


def _build_source_case_id(name_last: str, name_first: str, date_iso: str | None) -> str:
    date_part = date_iso or "undated"
    return f"mn-{_slugify(name_last)}-{_slugify(name_first)}-{date_part}"


def parse_harvest(path: Path) -> list[HarvestRecord]:
    """Parse + validate the harvest JSON file into HarvestRecord objects.

    Filters to `ContentType == 'Unsolved Homicide'`. Raises HarvestError on
    an empty harvest, a record missing a required field, or a duplicate
    synthesized source_case_id.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarvestError(f"could not read harvest file {path}: {exc!r}") from exc

    if not isinstance(raw, list):
        raise HarvestError(f"harvest must be a JSON array, got {type(raw).__name__}")

    in_scope = [r for r in raw if r.get("ContentType") == _IN_SCOPE_CONTENT_TYPE]
    if not in_scope:
        raise HarvestError(
            f"harvest is empty (0 '{_IN_SCOPE_CONTENT_TYPE}' records in {path})"
        )

    records: list[HarvestRecord] = []
    seen_ids: set[str] = set()
    for idx, r in enumerate(in_scope):
        missing = [f for f in _REQUIRED_FIELDS if not r.get(f)]
        if missing:
            raise HarvestError(
                f"harvest record {idx} ({r.get('NameLast')!r}) missing "
                f"required field(s): {', '.join(missing)}"
            )

        date_iso = normalize_date(str(r["Date1"]))
        scid = _build_source_case_id(
            name_last=str(r["NameLast"]),
            name_first=str(r["NameFirst"]),
            date_iso=date_iso,
        )
        if scid in seen_ids:
            raise HarvestError(f"duplicate synthesized source_case_id: {scid!r}")
        seen_ids.add(scid)

        age = r.get("Age")
        records.append(
            HarvestRecord(
                source_case_id=scid,
                name_first=str(r["NameFirst"]).strip(),
                name_middle=(str(r["NameMiddle"]).strip() if r.get("NameMiddle") else None),
                name_last=str(r["NameLast"]).strip(),
                name_suffix=(str(r["NameSuffix"]).strip() if r.get("NameSuffix") else None),
                age=(str(age).strip() if age not in (None, "") else None),
                incident_date_raw=str(r["Date1"]),
                incident_date_iso=date_iso,
                date_of_birth=(str(r["DateOfBirth"]).strip() if r.get("DateOfBirth") else None),
                location_city=(str(r["LocationCity"]).strip() if r.get("LocationCity") else None),
                location_county=(
                    str(r["LocationCounty"]).strip() if r.get("LocationCounty") else None
                ),
                location_state=(
                    str(r["LocationState"]).strip() if r.get("LocationState") else None
                ),
                pdf_path=str(r["PDF"]).strip(),
                picture_path=(str(r["Picture1"]).strip() if r.get("Picture1") else None),
                reward=(int(r["Reward"]) if isinstance(r.get("Reward"), (int, float)) else None),
            )
        )
    return records
