"""Parse NH DOJ Cold Case Unit /content/api/documents response.

Returns one IndexRecord per in-scope row (Unsolved Homicide or Suspicious
Death). Solved and Missing Person records are filtered out.

The API endpoint serves all 147 records in a single response when paginated
with size=200; we don't paginate further.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_DETAIL_URL_PREFIX = "https://www.doj.nh.gov"
_IN_SCOPE_CATEGORIES = frozenset({"Unsolved Homicide", "Suspicious Death"})

_YEAR_RE = re.compile(r"^\d{4}$")
_AGE_RE = re.compile(r"^age\s+(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class IndexRecord:
    """One in-scope row from the NH DOJ documents API."""

    title: str  # "Exampleton, Alex"
    slug: str  # "alex-exampleton"
    detail_url: str  # full absolute URL
    category_label: str  # "Unsolved Homicide" | "Suspicious Death"
    year_tag: str | None  # "1993"
    town_tag: str | None  # "manchester" — lowercased as stored in the source
    age_tag: str | None  # "30"


def _extract_link(fields: dict[str, object]) -> str | None:
    """Return a leading-slash path for the detail URL.

    Most records use a relative path like
    ``/bureaus/cold-case-unit/victim-list/alex-exampleton``.  A small
    number use an absolute URL of the form
    ``https://www.doj.nh.gov/node/65796``; we normalize those to
    ``/node/65796`` so the caller can prepend the host uniformly.
    """
    link = fields.get("field_link_url")
    if not isinstance(link, list) or not link:
        return None
    v = link[0]
    if not isinstance(v, str) or not v:
        return None
    if v.startswith("/"):
        return v
    if v.startswith(_DETAIL_URL_PREFIX + "/"):
        return v[len(_DETAIL_URL_PREFIX):]
    return None


def _category(fields: dict[str, object]) -> str | None:
    cat = fields.get("field_document_category")
    if isinstance(cat, list) and cat:
        first = cat[0]
        if isinstance(first, dict):
            title = first.get("title")
            if isinstance(title, str):
                return title
    return None


def _tags(fields: dict[str, object]) -> list[str]:
    tags = fields.get("field_entity_tags")
    if not isinstance(tags, list):
        return []
    out = []
    for t in tags:
        if not isinstance(t, dict):
            continue
        sub = t.get("fields")
        if not isinstance(sub, dict):
            continue
        name = sub.get("name")
        if isinstance(name, list) and name and isinstance(name[0], str):
            out.append(name[0])
    return out


def _classify_tags(tag_names: list[str]) -> tuple[str | None, str | None, str | None]:
    """Return (year, town, age) from the unordered tag list.

    Year is a 4-digit string; age matches `age N`; the remaining tag is town.
    """
    year: str | None = None
    age: str | None = None
    town: str | None = None
    leftovers: list[str] = []
    for name in tag_names:
        if _YEAR_RE.match(name):
            year = name
            continue
        am = _AGE_RE.match(name)
        if am:
            age = am.group(1)
            continue
        leftovers.append(name)
    if leftovers:
        # Multiple leftovers: prefer the first. Source consistently uses
        # one town tag per record.
        town = leftovers[0]
    return year, town, age


def parse_index_response(body: str) -> list[IndexRecord]:
    payload = json.loads(body)
    data = payload.get("data") or []
    out: list[IndexRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields")
        if not isinstance(fields, dict):
            continue
        title_list = fields.get("title")
        if not isinstance(title_list, list) or not title_list:
            continue
        title = title_list[0]
        if not isinstance(title, str):
            continue
        category = _category(fields)
        if category not in _IN_SCOPE_CATEGORIES:
            continue
        link = _extract_link(fields)
        if not link:
            continue
        slug = link.rsplit("/", 1)[-1]
        year, town, age = _classify_tags(_tags(fields))
        out.append(
            IndexRecord(
                title=title,
                slug=slug,
                detail_url=f"{_DETAIL_URL_PREFIX}{link}",
                category_label=category,
                year_tag=year,
                town_tag=town,
                age_tag=age,
            )
        )
    return out
