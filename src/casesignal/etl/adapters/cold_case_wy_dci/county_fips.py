"""Wyoming county-name → FIPS lookup.

23 counties (Census 2020). Tolerates "X County" suffix and case variants.
The Wyoming DCI source data uses "Jackson County" for cases in Teton County
(Jackson is the seat of Teton); aliased through.
"""

_FIPS_BY_NAME: dict[str, str] = {
    "albany": "56001",
    "big horn": "56003",
    "campbell": "56005",
    "carbon": "56007",
    "converse": "56009",
    "crook": "56011",
    "fremont": "56013",
    "goshen": "56015",
    "hot springs": "56017",
    "johnson": "56019",
    "laramie": "56021",
    "lincoln": "56023",
    "natrona": "56025",
    "niobrara": "56027",
    "park": "56029",
    "platte": "56031",
    "sheridan": "56033",
    "sublette": "56035",
    "sweetwater": "56037",
    "teton": "56039",
    "uinta": "56041",
    "washakie": "56043",
    "weston": "56045",
    # Alias: WY DCI uses "Jackson County" for cases in Teton (Jackson = town in Teton).
    "jackson": "56039",
    "jackson county": "56039",
}


def lookup(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    if key.endswith(" county") and key not in _FIPS_BY_NAME:
        key = key[: -len(" county")]
    return _FIPS_BY_NAME.get(key)
