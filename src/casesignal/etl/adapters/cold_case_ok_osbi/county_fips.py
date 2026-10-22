"""Oklahoma county-name → FIPS lookup + narrative county extractor.

77 Oklahoma counties, FIPS prefix 40 (state) + 3-digit county code per the
2020 Census. Values match data/static/county_centroids.csv (the same file the
county-centroid geocoding tier reads), so every FIPS resolves to a centroid.
Lookup is case-insensitive and tolerates a trailing 'County'.

OSBI publishes no structured county field — location lives in narrative prose.
county_from_narrative pulls an explicit "<Name> County" mention (~30% of
narratives name one; the rest name a city and are left to Tier-2 + Google).
"""

from __future__ import annotations

import re

# 77 counties, alphabetical, 5-digit FIPS (40 = OK, then 3-digit county).
OK_COUNTY_FIPS: dict[str, str] = {
    "Adair": "40001",
    "Alfalfa": "40003",
    "Atoka": "40005",
    "Beaver": "40007",
    "Beckham": "40009",
    "Blaine": "40011",
    "Bryan": "40013",
    "Caddo": "40015",
    "Canadian": "40017",
    "Carter": "40019",
    "Cherokee": "40021",
    "Choctaw": "40023",
    "Cimarron": "40025",
    "Cleveland": "40027",
    "Coal": "40029",
    "Comanche": "40031",
    "Cotton": "40033",
    "Craig": "40035",
    "Creek": "40037",
    "Custer": "40039",
    "Delaware": "40041",
    "Dewey": "40043",
    "Ellis": "40045",
    "Garfield": "40047",
    "Garvin": "40049",
    "Grady": "40051",
    "Grant": "40053",
    "Greer": "40055",
    "Harmon": "40057",
    "Harper": "40059",
    "Haskell": "40061",
    "Hughes": "40063",
    "Jackson": "40065",
    "Jefferson": "40067",
    "Johnston": "40069",
    "Kay": "40071",
    "Kingfisher": "40073",
    "Kiowa": "40075",
    "Latimer": "40077",
    "Le Flore": "40079",
    "Lincoln": "40081",
    "Logan": "40083",
    "Love": "40085",
    "Major": "40093",
    "Marshall": "40095",
    "Mayes": "40097",
    "McClain": "40087",
    "McCurtain": "40089",
    "McIntosh": "40091",
    "Murray": "40099",
    "Muskogee": "40101",
    "Noble": "40103",
    "Nowata": "40105",
    "Okfuskee": "40107",
    "Oklahoma": "40109",
    "Okmulgee": "40111",
    "Osage": "40113",
    "Ottawa": "40115",
    "Pawnee": "40117",
    "Payne": "40119",
    "Pittsburg": "40121",
    "Pontotoc": "40123",
    "Pottawatomie": "40125",
    "Pushmataha": "40127",
    "Roger Mills": "40129",
    "Rogers": "40131",
    "Seminole": "40133",
    "Sequoyah": "40135",
    "Stephens": "40137",
    "Texas": "40139",
    "Tillman": "40141",
    "Tulsa": "40143",
    "Wagoner": "40145",
    "Washington": "40147",
    "Washita": "40149",
    "Woods": "40151",
    "Woodward": "40153",
}

# Reverse of OK_COUNTY_FIPS, for rendering a human-readable geocoding_job
# address_text ("<Name> County, OK") from a resolved FIPS code.
_FIPS_TO_NAME = {fips: name for name, fips in OK_COUNTY_FIPS.items()}

# Space-insensitive, case-folded index. OSBI narratives spell "Le Flore" as
# "LeFlore" / "Leflore" (verified in the captured fixtures), so a case-only
# match dropped those and let a later county mention win the geocoding floor.
# Normalizing on (no spaces, lowercased) resolves every spelling to one FIPS
# and makes lookup O(1). No two OK counties collide under this normalization.
_NORMALIZED_TO_FIPS = {
    name.replace(" ", "").lower(): fips for name, fips in OK_COUNTY_FIPS.items()
}


def name_for_fips(fips: str) -> str | None:
    """FIPS -> canonical county name, or None if unknown."""
    return _FIPS_TO_NAME.get(fips)

# One or two capitalized tokens immediately before "County". finditer yields
# matches in DOCUMENT ORDER, so the earliest county named wins.
_COUNTY_MENTION_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?) County\b")


def lookup(county_name: str | None) -> str | None:
    """County name -> FIPS. Case-insensitive AND space-insensitive, so
    'Le Flore', 'LeFlore' and 'Leflore' all resolve to the same county.
    Tolerates a trailing 'County'. Returns None on empty/None/unknown.
    """
    if not county_name:
        return None
    cleaned = county_name.strip()
    if cleaned.lower().endswith(" county"):
        cleaned = cleaned[: -len(" county")].strip()
    return _NORMALIZED_TO_FIPS.get(cleaned.replace(" ", "").lower())


def county_from_narrative(text: str | None) -> str | None:
    """FIPS of the EARLIEST OK county named in the narrative, else None.

    Scans '<Words> County' mentions in document order. The captured one or two
    capitalized tokens are resolved as-is via ``lookup`` (which is space- and
    case-insensitive, so 'Le Flore'/'Roger Mills' spaced, 'LeFlore'/'Leflore'
    concatenated, and single names all resolve). The FIRST mention that
    resolves wins, so an earlier county is never overridden by a later one
    (e.g. a body found in one county but moved to another). A capitalized word
    that is not part of a real county name (e.g. 'West' in 'West Cleveland
    County') simply fails to resolve and the scan moves on — it is never
    reduced to a bare trailing token, which would fabricate a false match.
    """
    if not text:
        return None
    for m in _COUNTY_MENTION_RE.finditer(text):
        fips = lookup(m.group(1))
        if fips is not None:
            return fips
    return None
