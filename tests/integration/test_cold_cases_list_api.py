"""GET /api/v1/cold-cases — paginated list endpoint.

Self-seeding: seeds two synthetic corpora once per module (ZZ-state via
LIST_API_TEST, YY-state via LIST_API_TEST_2); every assertion is scoped to
those states or source codes so the module is fully isolated from historical
data in the dev DB.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tests.integration._seed import CaseSpec, ExtractionSpec, SeededCorpus, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

# ---------------------------------------------------------------------------
# Module-level corpus design
# ---------------------------------------------------------------------------
#
# 12 cases, state="ZZ", source_code="LIST_API_TEST".
#
# Designed so EVERY tested sort order, filter, and search has a deterministic,
# corpus-unique answer without touching any real seed data.
#
# Invariants table:
#
#  key    │ type              │ city   │ incident_date │ victim_name   │ gender │ race     │ weapon       │ location_type │ precision
#  ───────┼───────────────────┼────────┼───────────────┼───────────────┼────────┼──────────┼──────────────┼───────────────┼──────────
#  lst-01 │ homicide          │ Alpha  │ 2001-01-15    │ Alice Jordan  │ female │ Black    │ firearm      │ residence     │ street
#  lst-02 │ homicide          │ Beta   │ 2005-06-20    │ Bob Cooper    │ male   │ White    │ knife        │ public_outdoor│ landmark
#  lst-03 │ homicide          │ Alpha  │ 2010-03-10    │ Carol Davis   │ female │ hispanic │ firearm      │ vehicle       │ street
#  lst-04 │ homicide          │ Gamma  │ 2015-09-01    │ Dan Evans     │ male   │ Black    │ blunt        │ commercial    │ landmark
#  lst-05 │ suspicious_death  │ Beta   │ 2018-07-04    │ Eve Foster    │ female │ White    │ (none)       │ residence     │ street
#  lst-06 │ homicide          │ Gamma  │ 2020-12-31    │ Frank Green   │ male   │ hispanic │ knife        │ public_outdoor│ landmark
#  lst-07 │ homicide          │ Alpha  │ 2000-11-11    │ Grace Harris  │ female │ White    │ firearm      │ residence     │ street
#  lst-08 │ homicide          │ Delta  │ 2008-04-22    │ Harry Irving  │ male   │ Black    │ (NO extract) │ (NO extract)  │ landmark
#  lst-09 │ suspicious_death  │ Beta   │ 2012-02-29    │ Iris Jackson  │ female │ hispanic │ knife        │ vehicle       │ street
#  lst-10 │ homicide          │ Delta  │ 2003-08-08    │ (unnamed)     │ -      │ -        │ blunt        │ commercial    │ landmark
#  lst-11 │ homicide          │ Gamma  │ 2007-05-17    │ Jan Kelly     │ female │ White    │ firearm      │ residence     │ street
#  lst-12 │ homicide          │ Alpha  │ 2016-11-30    │ (no victim)   │ -      │ -        │ knife        │ public_outdoor│ landmark
#
# Key invariants:
#  - "jordan" is unique to victim Alice Jordan (lst-01) → ?q=jordan test
#  - source_case_id "LST-001"…"LST-012": deterministic COLLATE-C order
#  - lst-08 has NO extraction row → LEFT JOIN returns NULL weapon/location
#  - lst-10 victim has first_name=None + last_name=None → victim_primary_name=NULL
#  - lst-12 has no victim rows at all
#  - firearm: lst-01,03,07,11 (4); knife: lst-02,06,09,12 (4); blunt: lst-04,10 (2)
#  - residence: lst-01,05,07,11 (4); public_outdoor: lst-02,06,12 (3); vehicle: lst-03,09 (2); commercial: lst-04,10 (2)
#  - homicide: 10 (lst-01…04,06…08,10…12); suspicious_death: 2 (lst-05,lst-09)
#  - city Alpha: lst-01,03,07,12 (4); Beta: lst-02,05,09 (3); Gamma: lst-04,06,11 (3); Delta: lst-08,10 (2)
#  - year_min=2010,year_max=2015 → lst-03(2010), lst-04(2015), lst-09(2012) = 3 cases
#  - Black victims: lst-01,04,08 (3); White: lst-02,05,07,11 (4); hispanic: lst-03,06,09 (3)
#  - female: lst-01,03,05,07,09,11 (6); male: lst-02,04,06,08 (4)
#  - precision street: lst-01,03,05,07,09,11 (6); landmark: lst-02,04,06,08,10,12 (6)
#
# victim_primary_name sort (COLLATE "C" ASC NULLS LAST, case_id ASC):
#   "Alice Jordan" < "Bob Cooper" < "Carol Davis" < "Dan Evans" < "Eve Foster"
#   < "Frank Green" < "Grace Harris" < "Harry Irving" < "Iris Jackson" < "Jan Kelly"
#   then NULL (lst-10 unnamed victim, lst-12 no victim) → NULLs last

_CASES: list[CaseSpec] = [
    # lst-01: homicide, Alpha, 2001-01-15, Alice Jordan (female, Black), firearm, residence, street
    CaseSpec(
        source_case_id="LST-001",
        case_name="List API Test Homicide 01",
        state="ZZ",
        case_type="homicide",
        city="Alpha",
        incident_date="2001-01-15",
        victims=[
            VictimSpec(
                first_name="Alice",
                last_name="Jordan",
                gender="female",
                race="Black",
                age_text="34",
            )
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
        geocode_precision="street",
    ),
    # lst-02: homicide, Beta, 2005-06-20, Bob Cooper (male, White), knife, public_outdoor, landmark
    CaseSpec(
        source_case_id="LST-002",
        case_name="List API Test Homicide 02",
        state="ZZ",
        case_type="homicide",
        city="Beta",
        incident_date="2005-06-20",
        victims=[VictimSpec(first_name="Bob", last_name="Cooper", gender="male", race="White")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type="public_outdoor")],
        geocode_precision="landmark",
    ),
    # lst-03: homicide, Alpha, 2010-03-10, Carol Davis (female, hispanic), firearm, vehicle, street
    CaseSpec(
        source_case_id="LST-003",
        case_name="List API Test Homicide 03",
        state="ZZ",
        case_type="homicide",
        city="Alpha",
        incident_date="2010-03-10",
        victims=[
            VictimSpec(first_name="Carol", last_name="Davis", gender="female", race="hispanic")
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="vehicle")],
        geocode_precision="street",
    ),
    # lst-04: homicide, Gamma, 2015-09-01, Dan Evans (male, Black), blunt, commercial, landmark
    CaseSpec(
        source_case_id="LST-004",
        case_name="List API Test Homicide 04",
        state="ZZ",
        case_type="homicide",
        city="Gamma",
        incident_date="2015-09-01",
        victims=[VictimSpec(first_name="Dan", last_name="Evans", gender="male", race="Black")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="blunt", location_type="commercial")],
        geocode_precision="landmark",
    ),
    # lst-05: suspicious_death, Beta, 2018-07-04, Eve Foster (female, White), no weapon, residence, street
    CaseSpec(
        source_case_id="LST-005",
        case_name="List API Test SuspDeath 05",
        state="ZZ",
        case_type="suspicious_death",
        city="Beta",
        incident_date="2018-07-04",
        victims=[VictimSpec(first_name="Eve", last_name="Foster", gender="female", race="White")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon=None, location_type="residence")],
        geocode_precision="street",
    ),
    # lst-06: homicide, Gamma, 2020-12-31, Frank Green (male, hispanic), knife, public_outdoor, landmark
    CaseSpec(
        source_case_id="LST-006",
        case_name="List API Test Homicide 06",
        state="ZZ",
        case_type="homicide",
        city="Gamma",
        incident_date="2020-12-31",
        victims=[VictimSpec(first_name="Frank", last_name="Green", gender="male", race="hispanic")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type="public_outdoor")],
        geocode_precision="landmark",
    ),
    # lst-07: homicide, Alpha, 2000-11-11, Grace Harris (female, White), firearm, residence, street
    CaseSpec(
        source_case_id="LST-007",
        case_name="List API Test Homicide 07",
        state="ZZ",
        case_type="homicide",
        city="Alpha",
        incident_date="2000-11-11",
        victims=[VictimSpec(first_name="Grace", last_name="Harris", gender="female", race="White")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
        geocode_precision="street",
    ),
    # lst-08: homicide, Delta, 2008-04-22, Harry Irving (male, Black), NO extraction row, landmark
    CaseSpec(
        source_case_id="LST-008",
        case_name="List API Test Homicide 08 NoExtract",
        state="ZZ",
        case_type="homicide",
        city="Delta",
        incident_date="2008-04-22",
        victims=[VictimSpec(first_name="Harry", last_name="Irving", gender="male", race="Black")],
        extractions=[],  # intentionally no extraction row
        geocode_precision="landmark",
    ),
    # lst-09: suspicious_death, Beta, 2012-02-29, Iris Jackson (female, hispanic), knife, vehicle, street
    CaseSpec(
        source_case_id="LST-009",
        case_name="List API Test SuspDeath 09",
        state="ZZ",
        case_type="suspicious_death",
        city="Beta",
        incident_date="2012-02-29",
        victims=[
            VictimSpec(first_name="Iris", last_name="Jackson", gender="female", race="hispanic")
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type="vehicle")],
        geocode_precision="street",
    ),
    # lst-10: homicide, Delta, 2003-08-08, unnamed victim (first/last=None), blunt, commercial, landmark
    CaseSpec(
        source_case_id="LST-010",
        case_name="List API Test Homicide 10 Unnamed",
        state="ZZ",
        case_type="homicide",
        city="Delta",
        incident_date="2003-08-08",
        victims=[VictimSpec(first_name=None, last_name=None, gender=None, race=None)],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="blunt", location_type="commercial")],
        geocode_precision="landmark",
    ),
    # lst-11: homicide, Gamma, 2007-05-17, Jan Kelly (female, White), firearm, residence, street
    CaseSpec(
        source_case_id="LST-011",
        case_name="List API Test Homicide 11",
        state="ZZ",
        case_type="homicide",
        city="Gamma",
        incident_date="2007-05-17",
        victims=[VictimSpec(first_name="Jan", last_name="Kelly", gender="female", race="White")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
        geocode_precision="street",
    ),
    # lst-12: homicide, Alpha, 2016-11-30, NO victim rows, knife, public_outdoor, landmark
    CaseSpec(
        source_case_id="LST-012",
        case_name="List API Test Homicide 12 NoVictim",
        state="ZZ",
        case_type="homicide",
        city="Alpha",
        incident_date="2016-11-30",
        victims=[],  # intentionally no victims
        extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type="public_outdoor")],
        geocode_precision="landmark",
    ),
]

_N = len(_CASES)  # 12

# ---------------------------------------------------------------------------
# Second corpus: LIST_API_TEST_2 / state=YY
# 3 extra cases so multi-source union == 12+3 = 15, and single-source < total.
# ---------------------------------------------------------------------------

_YY_CASES: list[CaseSpec] = [
    CaseSpec(
        source_case_id="YY-001",
        case_name="List API Test YY Homicide 1",
        state="YY",
        case_type="homicide",
        city="Omega",
        incident_date="2009-03-01",
        victims=[VictimSpec(first_name="Yara", last_name="York", gender="female", race="White")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm", location_type="residence")],
        geocode_precision="street",
    ),
    CaseSpec(
        source_case_id="YY-002",
        case_name="List API Test YY Homicide 2",
        state="YY",
        case_type="homicide",
        city="Omega",
        incident_date="2013-06-15",
        victims=[VictimSpec(first_name="Yvonne", last_name="Yang", gender="female", race="Black")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon="knife", location_type="public_outdoor")],
        geocode_precision="landmark",
    ),
    CaseSpec(
        source_case_id="YY-003",
        case_name="List API Test YY SuspDeath 3",
        state="YY",
        case_type="suspicious_death",
        city="Omega",
        incident_date="2017-09-20",
        victims=[VictimSpec(first_name="Yoshi", last_name="Yuen", gender="male", race="hispanic")],
        extractions=[ExtractionSpec(prompt_tier=1, weapon=None, location_type="vehicle")],
        geocode_precision="street",
    ),
]

_N_YY = len(_YY_CASES)  # 3


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    """Seed the ZZ-state list-API corpus once for this module."""
    return seeded_corpus("LIST_API_TEST", _CASES)


@pytest.fixture(scope="module")
def corpus2(seeded_corpus: SeedFn) -> SeededCorpus:
    """Seed the YY-state list-API corpus once for this module."""
    return seeded_corpus("LIST_API_TEST_2", _YY_CASES)


# ---------------------------------------------------------------------------
# Pagination and param-validation tests
# ---------------------------------------------------------------------------


def test_list_default_params(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases?state=ZZ")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "meta" in body
    assert set(body["meta"].keys()) == {"total", "offset", "limit", "total_unfiltered"}
    assert body["meta"]["offset"] == 0
    assert body["meta"]["limit"] == 100
    assert body["meta"]["total"] >= len(body["data"])


def test_list_respects_limit_offset(public_client: TestClient, corpus: SeededCorpus) -> None:
    # Scoped to ZZ (12 cases) so pages are deterministic.
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=5&offset=0"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["limit"] == 5
    assert len(body["data"]) == 5  # 12 cases → first page is exactly 5

    r2 = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=5&offset=5"
    )
    assert r2.status_code == 200
    first_ids = {row["case_id"] for row in body["data"]}
    next_ids = {row["case_id"] for row in r2.json()["data"]}
    assert first_ids.isdisjoint(next_ids)


def test_list_total_independent_of_limit(public_client: TestClient, corpus: SeededCorpus) -> None:
    r1 = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=1")
    r2 = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=1000")
    assert r1.json()["meta"]["total"] == r2.json()["meta"]["total"]
    assert r1.json()["meta"]["total"] == _N


def test_list_rejects_limit_over_1000(public_client: TestClient) -> None:
    r = public_client.get("/api/v1/cold-cases?limit=1001")
    assert r.status_code == 422


def test_list_rejects_limit_zero(public_client: TestClient) -> None:
    r = public_client.get("/api/v1/cold-cases?limit=0")
    assert r.status_code == 422


def test_list_rejects_negative_offset(public_client: TestClient) -> None:
    r = public_client.get("/api/v1/cold-cases?offset=-1")
    assert r.status_code == 422


def test_list_accepts_known_sort(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&sort=incident_date_desc"
    )
    assert r.status_code == 200


def test_list_rejects_unknown_sort(public_client: TestClient) -> None:
    r = public_client.get("/api/v1/cold-cases?sort=something_random")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Shape tests
# ---------------------------------------------------------------------------


def test_list_item_shape(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 1, "ZZ corpus must return at least 1 row"
    row = body["data"][0]
    assert set(row.keys()) == {
        "case_id",
        "slug",
        "source_case_id",
        "case_name",
        "case_type",
        "incident_date",
        "city",
        "state",
        "victim_primary_name",
        "victim_primary_gender",
        "victim_primary_age",
        "victim_primary_race",
        "weapon",
        "weapon_low_confidence",
        "location_type",
        "location_type_low_confidence",
        "geocode_precision",
    }


def test_list_item_includes_primary_victim_demographics(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&sort=victim_name_asc&limit=50"
    )
    assert r.status_code == 200
    rows = r.json()["data"]
    alice = next(row for row in rows if row["victim_primary_name"] == "Alice Jordan")
    assert alice["victim_primary_gender"] == "female"
    assert alice["victim_primary_race"] == "Black"
    assert alice["victim_primary_age"] == 34  # age_num generated from age_text "34"


def test_list_item_extraction_field_types(public_client: TestClient, corpus: SeededCorpus) -> None:
    """weapon + location_type are nullable strings; low_confidence flags are bool."""
    r = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=20")
    body = r.json()
    assert len(body["data"]) > 0
    for row in body["data"]:
        assert row["weapon"] is None or isinstance(row["weapon"], str)
        assert isinstance(row["weapon_low_confidence"], bool)
        assert row["location_type"] is None or isinstance(row["location_type"], str)
        assert isinstance(row["location_type_low_confidence"], bool)


def test_list_item_includes_victim_name_and_source_id(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    r = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=50")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == _N

    # Every row has a source_case_id
    non_empty_source = [row for row in body["data"] if row["source_case_id"]]
    assert len(non_empty_source) == _N

    # victim_primary_name field present on every row; may be None for unnamed/no-victim
    for row in body["data"]:
        assert "victim_primary_name" in row
        assert row["victim_primary_name"] is None or isinstance(row["victim_primary_name"], str)


# ---------------------------------------------------------------------------
# Weapon / location_type filter tests
# ---------------------------------------------------------------------------


def test_list_filters_by_weapon(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?weapon=firearm narrows to firearm-classified cases in ZZ corpus."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&weapon=firearm&limit=20"
    )
    assert r.status_code == 200
    body = r.json()
    # lst-01,03,07,11 have firearm → 4 cases
    assert len(body["data"]) == 4
    for item in body["data"]:
        assert item["weapon"] == "firearm"


def test_list_filters_by_multiple_weapons(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?weapon=firearm,knife is OR within the dimension."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&weapon=firearm,knife&limit=50"
    )
    assert r.status_code == 200
    body = r.json()
    # firearm: lst-01,03,07,11 (4) + knife: lst-02,06,09,12 (4) = 8 (disjoint)
    assert body["meta"]["total"] == 8
    for item in body["data"]:
        assert item["weapon"] in ("firearm", "knife")


def test_list_filters_by_location_type(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?location_type=residence narrows to residence-classified cases."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&location_type=residence&limit=20"
    )
    assert r.status_code == 200
    body = r.json()
    # lst-01,05,07,11 have residence extraction → 4 cases
    assert body["meta"]["total"] == 4
    for item in body["data"]:
        assert item["location_type"] == "residence"


def test_list_no_mo_filter_still_returns_unextracted_cases(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """Without MO filter, LEFT JOIN includes cases without extraction rows
    (lst-08 has no extraction row — weapon/location_type come back NULL)."""
    r = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=50")
    body = r.json()
    # All 12 cases must appear
    assert body["meta"]["total"] == _N
    # Find lst-08 (no extraction row)
    item = next(
        (i for i in body["data"] if i["source_case_id"] == "LST-008"),
        None,
    )
    assert item is not None, "lst-08 (no extraction) must appear without MO filter"
    assert item["weapon"] is None
    assert item["weapon_low_confidence"] is False
    assert item["location_type"] is None
    assert item["location_type_low_confidence"] is False


def test_list_with_mo_filter_excludes_unextracted_cases(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """With MO filter active, lst-08 (no extraction row) is excluded — NULL
    never matches weapon = ANY(...) by SQL semantics."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&weapon=firearm&limit=50"
    )
    body = r.json()
    case_scids = {i["source_case_id"] for i in body["data"]}
    assert "LST-008" not in case_scids, "unextracted case must NOT appear under weapon filter"
    # lst-05 also has null weapon → excluded too
    assert "LST-005" not in case_scids


# ---------------------------------------------------------------------------
# Sort tests
# ---------------------------------------------------------------------------


def test_list_sort_incident_date_desc_nulls_last(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&sort=incident_date_desc&limit=50"
    )
    rows = r.json()["data"]
    assert len(rows) == _N
    dated = [row for row in rows if row["incident_date"] is not None]
    nulls = [row for row in rows if row["incident_date"] is None]
    # All 12 seeded cases have incident_date — no nulls expected in our corpus
    assert len(dated) == _N
    assert len(nulls) == 0
    # Verify descending order: 2020-12-31 first, then 2018-07-04, …, 2000-11-11
    for i in range(len(dated) - 1):
        assert dated[i]["incident_date"] >= dated[i + 1]["incident_date"]
    # Spot-check: first must be 2020-12-31 (lst-06) and last must be 2000-11-11 (lst-07)
    assert dated[0]["incident_date"] == "2020-12-31"
    assert dated[-1]["incident_date"] == "2000-11-11"


def test_list_sort_victim_name_asc(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&sort=victim_name_asc&limit=50"
    )
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == _N
    # NULLS LAST: None victim sorts to end, represented by max char sentinel for comparison
    names = [(row["victim_primary_name"] or "￿") for row in rows]
    assert names == sorted(names), f"victim_name_asc not sorted: {names}"
    # Spot-check: Alice Jordan first (named), nulls (lst-10 unnamed + lst-12 no victim) last
    assert rows[0]["victim_primary_name"] == "Alice Jordan"
    assert rows[-1]["victim_primary_name"] is None
    assert rows[-2]["victim_primary_name"] is None


def test_list_sort_source_case_id_desc(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&sort=source_case_id_desc&limit=50"
    )
    assert r.status_code == 200
    ids = [row["source_case_id"] for row in r.json()["data"]]
    assert len(ids) == _N
    # COLLATE "C" DESC: LST-012 first, LST-001 last
    assert ids == sorted(ids, reverse=True), f"source_case_id_desc not sorted: {ids}"
    assert ids[0] == "LST-012"
    assert ids[-1] == "LST-001"


def test_list_sort_invalid_returns_422(public_client: TestClient) -> None:
    r = public_client.get("/api/v1/cold-cases?sort=banana")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


def test_list_search_matches_victim_last_name(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?q=jordan matches Alice Jordan in the ZZ corpus (unique to this corpus)."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&q=jordan&limit=50"
    )
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) > 0
    assert all("jordan" in (row["victim_primary_name"] or "").lower() for row in rows)
    # Exactly lst-01 in the ZZ corpus
    assert rows[0]["source_case_id"] == "LST-001"


def test_list_search_matches_source_case_id(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?q=LST-008 matches by source_case_id prefix."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&q=LST-008&limit=50"
    )
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) >= 1
    assert any(row["source_case_id"] == "LST-008" for row in rows)


def test_list_search_too_short_returns_422(public_client: TestClient) -> None:
    r = public_client.get("/api/v1/cold-cases?q=a")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Meta tests
# ---------------------------------------------------------------------------


def test_list_meta_includes_total_unfiltered(public_client: TestClient, corpus: SeededCorpus) -> None:
    """total_unfiltered equals total when no filters are applied (scoped to ZZ corpus)."""
    r = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=1")
    assert r.status_code == 200
    body = r.json()
    assert "total_unfiltered" in body["meta"]
    # state+source_system filters narrow total; total_unfiltered is the global DB count
    assert body["meta"]["total"] == _N  # scoped total
    assert body["meta"]["total_unfiltered"] > 0  # always > 0 (DB has real data too)


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------


def test_list_filter_case_type_single(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?case_type=homicide returns only homicide rows in ZZ corpus."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&case_type=homicide&limit=50"
    )
    assert r.status_code == 200
    body = r.json()
    # 10 homicides in ZZ corpus
    assert body["meta"]["total"] == 10
    assert all(row["case_type"] == "homicide" for row in body["data"])
    # Filtered total <= scoped unfiltered (total before the case_type filter)
    full = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=50"
    ).json()
    assert body["meta"]["total"] <= full["meta"]["total"]


def test_list_filter_case_type_multi_value(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?case_type=homicide,suspicious_death returns both types from ZZ corpus."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST"
        "&case_type=homicide,suspicious_death&limit=50"
    )
    body = r.json()
    # All 12 ZZ cases match (homicide=10 + suspicious_death=2)
    assert body["meta"]["total"] == _N
    returned_ids = {row["source_case_id"] for row in body["data"]}
    expected_ids = {c.source_case_id for c in _CASES}
    assert returned_ids == expected_ids


def test_list_filter_year_range(public_client: TestClient, corpus: SeededCorpus) -> None:
    """year_min=2010&year_max=2015 → lst-03(2010), lst-04(2015), lst-09(2012) = 3."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST"
        "&year_min=2010&year_max=2015&limit=50"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 3
    returned_scids = {row["source_case_id"] for row in body["data"]}
    assert returned_scids == {"LST-003", "LST-004", "LST-009"}
    for row in body["data"]:
        assert row["incident_date"] is not None
        year = int(row["incident_date"][:4])
        assert 2010 <= year <= 2015


def test_list_filter_city_case_sensitive(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?city=Alpha narrows to ZZ-corpus Alpha cases (lst-01,03,07,12 = 4)."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&city=Alpha&limit=50"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 4
    for row in body["data"]:
        assert row["city"] == "Alpha"


def test_list_filter_state(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?state=ZZ returns only ZZ-state rows."""
    r = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=50")
    assert r.status_code == 200
    for row in r.json()["data"]:
        assert row["state"] == "ZZ"


def test_list_filter_combined_with_pagination(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Combined case_type + pagination: pages are disjoint, total is consistent."""
    # 10 homicides in ZZ corpus → can paginate with limit=3
    page1 = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&case_type=homicide&limit=3&offset=0"
    ).json()
    page2 = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&case_type=homicide&limit=3&offset=3"
    ).json()

    assert page1["meta"]["total"] == 10
    assert page2["meta"]["total"] == 10
    p1_ids = {r["case_id"] for r in page1["data"]}
    p2_ids = {r["case_id"] for r in page2["data"]}
    assert p1_ids.isdisjoint(p2_ids)


def test_list_filter_empty_csv_no_op(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Empty/whitespace CSV treated as 'no filter applied' (_split_csv behavior)."""
    baseline = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=1"
    ).json()
    empty = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&case_type=&limit=1"
    ).json()
    whitespace = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&case_type=%20%20&limit=1"
    ).json()
    assert empty["meta"]["total"] == baseline["meta"]["total"]
    assert whitespace["meta"]["total"] == baseline["meta"]["total"]


def test_list_filter_victim_race_multivalue(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?race=White,Black returns the union of both races in ZZ corpus."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&race=White,Black&limit=50"
    )
    assert r.status_code == 200
    body = r.json()
    # White: lst-02,05,07,11 (4); Black: lst-01,04,08 (3) → 7 cases (disjoint)
    assert body["meta"]["total"] == 7
    returned_scids = {row["source_case_id"] for row in body["data"]}
    assert returned_scids == {
        "LST-001",
        "LST-002",
        "LST-004",
        "LST-005",
        "LST-007",
        "LST-008",
        "LST-011",
    }


# ---------------------------------------------------------------------------
# Source-system filter tests
# ---------------------------------------------------------------------------


def test_list_filters_by_source_system(
    public_client: TestClient, corpus: SeededCorpus, corpus2: SeededCorpus
) -> None:
    """source_system=LIST_API_TEST narrows results vs. unfiltered total (both corpora present)."""
    r_ss = public_client.get("/api/v1/cold-cases?source_system=LIST_API_TEST&limit=50")
    assert r_ss.status_code == 200
    data = r_ss.json()
    assert data["meta"]["total"] == _N  # exactly ZZ corpus
    # Filtered total must be strictly less than the global total
    assert data["meta"]["total"] < data["meta"]["total_unfiltered"]


def test_list_filters_by_multiple_source_systems(
    public_client: TestClient, corpus: SeededCorpus, corpus2: SeededCorpus
) -> None:
    """Comma-separated codes return union: count == sum of individual counts."""
    r_zz = public_client.get("/api/v1/cold-cases?source_system=LIST_API_TEST&limit=1")
    r_yy = public_client.get("/api/v1/cold-cases?source_system=LIST_API_TEST_2&limit=1")
    r_both = public_client.get(
        "/api/v1/cold-cases?source_system=LIST_API_TEST,LIST_API_TEST_2&limit=1"
    )
    assert r_zz.status_code == 200
    assert r_yy.status_code == 200
    assert r_both.status_code == 200

    count_zz = r_zz.json()["meta"]["total"]
    count_yy = r_yy.json()["meta"]["total"]
    count_both = r_both.json()["meta"]["total"]

    assert count_zz == _N  # 12
    assert count_yy == _N_YY  # 3
    # Sources are disjoint → union equals the sum
    assert count_both == count_zz + count_yy


def test_list_source_system_filter_narrows_result_set(
    public_client: TestClient, corpus: SeededCorpus, corpus2: SeededCorpus
) -> None:
    """Filtering by one source yields fewer results than filtering by both seeded sources."""
    r_both = public_client.get(
        "/api/v1/cold-cases?source_system=LIST_API_TEST,LIST_API_TEST_2&limit=1"
    )
    r_one = public_client.get("/api/v1/cold-cases?source_system=LIST_API_TEST&limit=1")
    assert r_both.status_code == 200
    assert r_one.status_code == 200

    total_both = r_both.json()["meta"]["total"]
    total_one = r_one.json()["meta"]["total"]

    assert total_both == _N + _N_YY  # 15 — both seeded corpora
    assert total_one == _N  # 12 — single-source filter
    assert total_one < total_both  # narrowing is genuine


def test_list_source_system_empty_csv_no_op(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Empty/whitespace source_system treated as no filter (_split_csv semantics)."""
    baseline = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&limit=1"
    ).json()
    # Empty source_system → no source filter; scoped by state=ZZ → same total
    empty = public_client.get("/api/v1/cold-cases?state=ZZ&source_system=&limit=1").json()
    assert empty["meta"]["total"] == baseline["meta"]["total"]


def test_list_source_system_unknown_code_returns_empty(public_client: TestClient) -> None:
    """An unknown source_system code matches no rows."""
    r = public_client.get("/api/v1/cold-cases?source_system=NONEXISTENT_SOURCE_CODE&limit=10")
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 0


# ---------------------------------------------------------------------------
# Precision filter tests
# ---------------------------------------------------------------------------


def test_list_precision_filter_single(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?precision=street narrows to street-precision geocoded cases in ZZ corpus."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&precision=street&limit=50"
    )
    assert r.status_code == 200
    data = r.json()
    # lst-01,03,05,07,09,11 → 6 street cases
    assert len(data["data"]) == 6
    for item in data["data"]:
        assert item.get("geocode_precision") == "street"


def test_list_precision_filter_multi(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?precision=street,landmark returns union of both tiers."""
    r = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&precision=street,landmark&limit=50"
    )
    assert r.status_code == 200
    data = r.json()
    # All 12 ZZ cases have either street or landmark
    assert len(data["data"]) == _N
    for item in data["data"]:
        assert item.get("geocode_precision") in ("street", "landmark")


# ---------------------------------------------------------------------------
# Gender / race filter tests
# ---------------------------------------------------------------------------


def test_list_gender_filter_accepts_either_form(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?gender=M and ?gender=male return the same set of ZZ cases."""
    r1 = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&gender=M&limit=50"
    )
    r2 = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&gender=male&limit=50"
    )
    assert r1.status_code == 200 and r2.status_code == 200
    # Both forms must return the same case_ids (lst-02,04,06,08 → 4 male-victim cases)
    ids1 = {row["case_id"] for row in r1.json()["data"]}
    ids2 = {row["case_id"] for row in r2.json()["data"]}
    assert ids1 == ids2
    assert len(ids1) == 4


def test_list_race_filter_case_insensitive(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?race=Black and ?race=BLACK return the same ZZ case set."""
    r1 = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&race=Black&limit=50"
    )
    r2 = public_client.get(
        "/api/v1/cold-cases?state=ZZ&source_system=LIST_API_TEST&race=BLACK&limit=50"
    )
    assert r1.status_code == 200 and r2.status_code == 200
    ids1 = {row["case_id"] for row in r1.json()["data"]}
    ids2 = {row["case_id"] for row in r2.json()["data"]}
    assert ids1 == ids2
    # lst-01,04,08 have Black victims → 3 cases
    assert len(ids1) == 3


def test_list_race_other_matches_unmapped_spellings(
    public_client: TestClient, seeded_corpus: SeedFn
) -> None:
    """The 'Other' bucket is a COMPLEMENT match: it returns cases whose race is
    not one of the specific NIBRS buckets — including a spelling absent from the
    canonical map. This keeps the Other filter consistent with the Other facet/
    count under data drift (a new spelling folds to Other in both). Codex P2.
    """
    seeded_corpus(
        "RACE_OTHER_TEST",
        [
            CaseSpec(
                source_case_id="ro-01",
                case_name="Race Other Unmapped",
                state="OZ",
                case_type="homicide",
                incident_date="1995-01-01",
                victims=[
                    VictimSpec(
                        first_name="Una", last_name="Mapped", gender="female", race="Zorblaxian"
                    )
                ],
            ),
            CaseSpec(
                source_case_id="ro-02",
                case_name="Race Other White",
                state="OZ",
                case_type="homicide",
                incident_date="1996-01-01",
                victims=[
                    VictimSpec(
                        first_name="Will", last_name="Hyte", gender="male", race="White"
                    )
                ],
            ),
        ],
    )

    other = public_client.get("/api/v1/cold-cases?state=OZ&race=Other&limit=50")
    assert other.status_code == 200
    other_scids = {row["source_case_id"] for row in other.json()["data"]}
    # The unmapped spelling folds to Other and IS returned; the mapped White is not.
    assert "ro-01" in other_scids
    assert "ro-02" not in other_scids

    white = public_client.get("/api/v1/cold-cases?state=OZ&race=White&limit=50")
    assert white.status_code == 200
    white_scids = {row["source_case_id"] for row in white.json()["data"]}
    assert white_scids == {"ro-02"}
