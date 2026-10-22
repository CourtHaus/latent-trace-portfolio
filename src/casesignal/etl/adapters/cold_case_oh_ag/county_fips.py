"""Ohio county-name → FIPS lookup.

88 Ohio counties, FIPS prefix 39 (state) + 3-digit county code per the
2020 Census. Sourced from the U.S. Census Bureau Gazetteer file
(2020 counties).

Lookup is case-insensitive and tolerates the 'County' suffix being
absent (e.g., 'Hamilton' resolves the same as 'Hamilton County').
"""

from __future__ import annotations

# 88 counties, alphabetical, 5-digit FIPS (39 = OH, then 3-digit county).
OH_COUNTY_FIPS: dict[str, str] = {
    "Adams": "39001",
    "Allen": "39003",
    "Ashland": "39005",
    "Ashtabula": "39007",
    "Athens": "39009",
    "Auglaize": "39011",
    "Belmont": "39013",
    "Brown": "39015",
    "Butler": "39017",
    "Carroll": "39019",
    "Champaign": "39021",
    "Clark": "39023",
    "Clermont": "39025",
    "Clinton": "39027",
    "Columbiana": "39029",
    "Coshocton": "39031",
    "Crawford": "39033",
    "Cuyahoga": "39035",
    "Darke": "39037",
    "Defiance": "39039",
    "Delaware": "39041",
    "Erie": "39043",
    "Fairfield": "39045",
    "Fayette": "39047",
    "Franklin": "39049",
    "Fulton": "39051",
    "Gallia": "39053",
    "Geauga": "39055",
    "Greene": "39057",
    "Guernsey": "39059",
    "Hamilton": "39061",
    "Hancock": "39063",
    "Hardin": "39065",
    "Harrison": "39067",
    "Henry": "39069",
    "Highland": "39071",
    "Hocking": "39073",
    "Holmes": "39075",
    "Huron": "39077",
    "Jackson": "39079",
    "Jefferson": "39081",
    "Knox": "39083",
    "Lake": "39085",
    "Lawrence": "39087",
    "Licking": "39089",
    "Logan": "39091",
    "Lorain": "39093",
    "Lucas": "39095",
    "Madison": "39097",
    "Mahoning": "39099",
    "Marion": "39101",
    "Medina": "39103",
    "Meigs": "39105",
    "Mercer": "39107",
    "Miami": "39109",
    "Monroe": "39111",
    "Montgomery": "39113",
    "Morgan": "39115",
    "Morrow": "39117",
    "Muskingum": "39119",
    "Noble": "39121",
    "Ottawa": "39123",
    "Paulding": "39125",
    "Perry": "39127",
    "Pickaway": "39129",
    "Pike": "39131",
    "Portage": "39133",
    "Preble": "39135",
    "Putnam": "39137",
    "Richland": "39139",
    "Ross": "39141",
    "Sandusky": "39143",
    "Scioto": "39145",
    "Seneca": "39147",
    "Shelby": "39149",
    "Stark": "39151",
    "Summit": "39153",
    "Trumbull": "39155",
    "Tuscarawas": "39157",
    "Union": "39159",
    "Van Wert": "39161",
    "Vinton": "39163",
    "Warren": "39165",
    "Washington": "39167",
    "Wayne": "39169",
    "Williams": "39171",
    "Wood": "39173",
    "Wyandot": "39175",
}


def lookup(county_name: str | None) -> str | None:
    """Case-insensitive county lookup, tolerates 'County' suffix.

    Returns None on empty/None input or unknown county.
    """
    if not county_name:
        return None
    cleaned = county_name.strip()
    if cleaned.lower().endswith(" county"):
        cleaned = cleaned[: -len(" county")].strip()
    for canonical, fips in OH_COUNTY_FIPS.items():
        if canonical.lower() == cleaned.lower():
            return fips
    return None
