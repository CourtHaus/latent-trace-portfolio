"""SEC-free: GIS cold-case map API — end-to-end via TestClient + real DB.

Self-seeding: seeds two synthetic corpora once per module (ZZ-state via
MAP_API_TEST, YY-state via MAP_API_TEST_2); every assertion is scoped to
those states or source codes, so the module is isolated from whatever
historical data the dev DB has loaded.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from casesignal.api.app import create_app
from casesignal.api.dependencies.auth import AuthenticatedKey, require_api_key
from tests.integration._seed import CaseSpec, SeededCorpus, SeedFn, VictimSpec

pytestmark = pytest.mark.integration

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

# ---------------------------------------------------------------------------
# Module-level corpus
# ---------------------------------------------------------------------------

# All seeded cases use state=ZZ — a synthetic state no real adapter uses.
# The bbox covers the entire planet so every seeded case is in-scope for
# map requests; combine with &state=ZZ to isolate from the historical corpus.
WORLD_BBOX = "-180,-90,180,90"
PACIFIC_BBOX = "-170,0,-150,20"

# Coordinates sit in the North-Atlantic for all seeded cases (state=ZZ) so
# they can't collide with real US data; each case gets a slightly different
# longitude to keep them distinct.
_ZZ_LAT = 40.0
_ZZ_LON_BASE = -20.0

# YY corpus: slightly different latitude band to avoid any coordinate collision
# with ZZ cases, still in the North-Atlantic and fully covered by WORLD_BBOX.
_YY_LAT = 41.0
_YY_LON_BASE = -21.0


def _lon(offset: float) -> float:
    return _ZZ_LON_BASE + offset


def _yy_lon(offset: float) -> float:
    return _YY_LON_BASE + offset


# 10-case corpus designed to exercise every filter and shape assertion:
#
#  case_id key │ type              │ gender  │ race      │ year │ age_text │ precision
#  ────────────┼───────────────────┼─────────┼───────────┼──────┼──────────┼───────────
#  hom-1       │ homicide          │ Female  │ hispanic  │ 2005 │ 20       │ street
#  hom-2       │ homicide          │ Male    │ White     │ 2010 │ 22       │ landmark
#  hom-3       │ homicide          │ Female  │ hispanic  │ 2012 │ 24       │ street
#  hom-4       │ homicide          │ Male    │ Black     │ 2015 │ 45       │ landmark
#  hom-5       │ homicide (multi-  │ Female  │ White     │ 2018 │ 30       │ street
#              │   victim)         │ + Male  │   + Black │      │          │
#  hom-6       │ homicide          │ (none)  │ (none)    │ 2020 │ (none)   │ landmark
#              │   (no victim)     │         │           │      │          │
#  sus-7       │ suspicious_death  │ Female  │ hispanic  │ 2008 │ 35       │ street
#  sus-8       │ suspicious_death  │ Male    │ White     │ 2014 │ 19       │ landmark
#  hom-9       │ homicide (named)  │ Female  │ Black     │ 2011 │ 28       │ street
#              │   victim w/ name  │         │           │      │          │
#  hom-10      │ homicide (unidfied│ (none-  │ (none)    │ 2013 │ (none)   │ landmark
#              │   primary victim  │  named) │           │      │          │
#
# Invariants:
#   - 3 cases with victim.race == 'hispanic' (hom-1, hom-3, sus-7)  → race filter
#   - 2 distinct case_types (homicide, suspicious_death)             → multi-type filter
#   - 2 distinct genders (Male, Female)                              → multi-gender filter
#   - ≥2 distinct races (hispanic, White, Black)                     → multi-race filter
#   - age_text 20/22/24/19 land in 18-25 range                      → age filter
#   - incident_dates span 2010-2015 (hom-2,hom-3,hom-4,hom-9,hom-10,sus-8) → year filter
#   - hom-5 has 2 victims                                            → double-count regression
#   - hom-6 has no victim                                            → disappears under gender filter
#   - hom-9 has first/last name                                      → victim_primary_name test
#   - hom-10 primary victim has no name                              → null primary_name test
#   - precision=street (hom-1,hom-3,hom-5,sus-7,hom-9)              → precision filter
#   - precision=landmark (hom-2,hom-4,hom-6,sus-8,hom-10)           → precision filter

_CASES: list[CaseSpec] = [
    # hom-1: female hispanic street 2005 age 20
    CaseSpec(
        source_case_id="hom-1",
        case_name="MAP API Test Homicide 1",
        state="ZZ",
        case_type="homicide",
        incident_date="2005-03-15",
        latitude=_ZZ_LAT,
        longitude=_lon(0.0),
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Alice",
                last_name="Alfa",
                gender="female",
                race="hispanic",
                age_text="20",
            )
        ],
    ),
    # hom-2: male White landmark 2010 age 22
    CaseSpec(
        source_case_id="hom-2",
        case_name="MAP API Test Homicide 2",
        state="ZZ",
        case_type="homicide",
        incident_date="2010-07-04",
        latitude=_ZZ_LAT,
        longitude=_lon(0.1),
        geocode_precision="landmark",
        victims=[
            VictimSpec(
                first_name="Bob", last_name="Bravo", gender="male", race="White", age_text="22"
            )
        ],
    ),
    # hom-3: female hispanic street 2012 age 24
    CaseSpec(
        source_case_id="hom-3",
        case_name="MAP API Test Homicide 3",
        state="ZZ",
        case_type="homicide",
        incident_date="2012-11-01",
        latitude=_ZZ_LAT,
        longitude=_lon(0.2),
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Carmen",
                last_name="Charlie",
                gender="female",
                race="hispanic",
                age_text="24",
            )
        ],
    ),
    # hom-4: male Black landmark 2015 age 45
    CaseSpec(
        source_case_id="hom-4",
        case_name="MAP API Test Homicide 4",
        state="ZZ",
        case_type="homicide",
        incident_date="2015-06-20",
        latitude=_ZZ_LAT,
        longitude=_lon(0.3),
        geocode_precision="landmark",
        victims=[
            VictimSpec(
                first_name="Dan", last_name="Delta", gender="male", race="Black", age_text="45"
            )
        ],
    ),
    # hom-5: multi-victim (female White + male Black) street 2018
    CaseSpec(
        source_case_id="hom-5",
        case_name="MAP API Test Homicide 5 Multi",
        state="ZZ",
        case_type="homicide",
        incident_date="2018-02-14",
        latitude=_ZZ_LAT,
        longitude=_lon(0.4),
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Eve", last_name="Echo", gender="female", race="White", age_text="30"
            ),
            VictimSpec(
                first_name="Frank", last_name="Foxtrot", gender="male", race="Black", age_text="32"
            ),
        ],
    ),
    # hom-6: no victim (for "disappears under demographic filter" test) landmark 2020
    CaseSpec(
        source_case_id="hom-6",
        case_name="MAP API Test Homicide 6 NoVictim",
        state="ZZ",
        case_type="homicide",
        incident_date="2020-09-01",
        latitude=_ZZ_LAT,
        longitude=_lon(0.5),
        geocode_precision="landmark",
        victims=[],
    ),
    # sus-7: suspicious_death female hispanic street 2008 age 35
    CaseSpec(
        source_case_id="sus-7",
        case_name="MAP API Test SuspDeath 7",
        state="ZZ",
        case_type="suspicious_death",
        incident_date="2008-05-10",
        latitude=_ZZ_LAT,
        longitude=_lon(0.6),
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Grace",
                last_name="Golf",
                gender="female",
                race="hispanic",
                age_text="35",
            )
        ],
    ),
    # sus-8: suspicious_death male White landmark 2014 age 19
    CaseSpec(
        source_case_id="sus-8",
        case_name="MAP API Test SuspDeath 8",
        state="ZZ",
        case_type="suspicious_death",
        incident_date="2014-08-22",
        latitude=_ZZ_LAT,
        longitude=_lon(0.7),
        geocode_precision="landmark",
        victims=[
            VictimSpec(
                first_name="Harry", last_name="Hotel", gender="male", race="White", age_text="19"
            )
        ],
    ),
    # hom-9: named victim female Black street 2011 age 28
    CaseSpec(
        source_case_id="hom-9",
        case_name="MAP API Test Homicide 9 Named",
        state="ZZ",
        case_type="homicide",
        incident_date="2011-04-01",
        latitude=_ZZ_LAT,
        longitude=_lon(0.8),
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Iris", last_name="India", gender="female", race="Black", age_text="28"
            )
        ],
    ),
    # hom-10: unnamed primary victim (no first/last name) landmark 2013
    CaseSpec(
        source_case_id="hom-10",
        case_name="MAP API Test Homicide 10 Unnamed",
        state="ZZ",
        case_type="homicide",
        incident_date="2013-01-15",
        latitude=_ZZ_LAT,
        longitude=_lon(0.9),
        geocode_precision="landmark",
        victims=[
            VictimSpec(first_name=None, last_name=None, gender=None, race=None, age_text=None)
        ],
    ),
]


# ---------------------------------------------------------------------------
# Second corpus: MAP_API_TEST_2 / state=YY
# ---------------------------------------------------------------------------
# 3 cases — enough to make filtered_total < unfiltered_total when combined
# with the ZZ corpus, and enough to prove the multi-source union.
_YY_CASES: list[CaseSpec] = [
    CaseSpec(
        source_case_id="yy-1",
        case_name="MAP API Test YY Homicide 1",
        state="YY",
        case_type="homicide",
        incident_date="2007-03-01",
        latitude=_YY_LAT,
        longitude=_yy_lon(0.0),
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Yara", last_name="York", gender="female", race="White", age_text="27"
            )
        ],
    ),
    CaseSpec(
        source_case_id="yy-2",
        case_name="MAP API Test YY Homicide 2",
        state="YY",
        case_type="homicide",
        incident_date="2011-06-15",
        latitude=_YY_LAT,
        longitude=_yy_lon(0.1),
        geocode_precision="landmark",
        victims=[
            VictimSpec(
                first_name="Yvonne", last_name="Yang", gender="female", race="Black", age_text="34"
            )
        ],
    ),
    CaseSpec(
        source_case_id="yy-3",
        case_name="MAP API Test YY SuspDeath 3",
        state="YY",
        case_type="suspicious_death",
        incident_date="2016-09-20",
        latitude=_YY_LAT,
        longitude=_yy_lon(0.2),
        geocode_precision="street",
        victims=[
            VictimSpec(
                first_name="Yoshi", last_name="Yuen", gender="male", race="hispanic", age_text="41"
            )
        ],
    ),
]


@pytest.fixture(scope="module")
def corpus(seeded_corpus: SeedFn) -> SeededCorpus:
    """Seed the ZZ-state map-API corpus once for this module."""
    return seeded_corpus("MAP_API_TEST", _CASES)


@pytest.fixture(scope="module")
def corpus2(seeded_corpus: SeedFn) -> SeededCorpus:
    """Seed the YY-state map-API corpus once for this module."""
    return seeded_corpus("MAP_API_TEST_2", _YY_CASES)


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def admin_client() -> Iterator[TestClient]:
    app = create_app()

    def override_key(request: Request) -> AuthenticatedKey:
        request.state.api_key_id = 999
        return AuthenticatedKey(key_id=999, role="admin")

    app.dependency_overrides[require_api_key] = override_key
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Basic bbox / shape tests
# ---------------------------------------------------------------------------


def test_world_bbox_zz_returns_seeded_rows(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """World bbox + state=ZZ must return exactly our 10 seeded cases."""
    resp = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == len(_CASES)
    assert body["meta"]["returned"] == len(_CASES)
    assert body["meta"]["truncated"] is False


def test_pacific_bbox_returns_empty(admin_client: TestClient, corpus: SeededCorpus) -> None:
    resp = admin_client.get(f"/api/v1/cold-cases/map?bbox={PACIFIC_BBOX}&state=ZZ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["returned"] == 0


def test_case_type_filter_narrows(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """Homicide filter on ZZ corpus must return only homicide rows (< total)."""
    resp_all = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    resp_hom = admin_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&case_type=homicide&limit=10000"
    )
    assert resp_all.status_code == 200
    assert resp_hom.status_code == 200
    hom_count = len(resp_hom.json()["data"])
    all_count = len(resp_all.json()["data"])
    # corpus has 8 homicides and 2 suspicious_deaths
    assert hom_count == 8
    assert 0 < hom_count < all_count
    for item in resp_hom.json()["data"]:
        assert item["case_type"] == "homicide"


def test_state_zz_filter(admin_client: TestClient, corpus: SeededCorpus) -> None:
    resp = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) > 0
    for item in data:
        assert item["state"] == "ZZ"


def test_state_xx_returns_empty(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """A state code with no seeded cases must return an empty result."""
    resp = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=XX")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ---------------------------------------------------------------------------
# Race / gender / age / year filter tests
# ---------------------------------------------------------------------------


def test_race_hispanic_filter_returns_matching(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """Scoped replacement for the old RACE_HISPANIC_COUNT canary.

    The ZZ corpus has exactly 3 hispanic-victim cases (hom-1, hom-3, sus-7).
    Filtering ?race=hispanic&state=ZZ must return exactly those 3.
    """
    resp = admin_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&race=hispanic&limit=10000"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 3
    returned_ids = {r["source_case_id"] for r in data}
    assert returned_ids == {"hom-1", "hom-3", "sus-7"}


def test_gender_female_filter(admin_client: TestClient, corpus: SeededCorpus) -> None:
    resp = admin_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&gender=female&limit=10000"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # corpus has female victims in hom-1, hom-3, hom-5, sus-7, hom-9
    assert len(data) >= 5
    # Every returned case must have at least one female victim; verify via source_case_id membership
    zz_female_scids = {"hom-1", "hom-3", "hom-5", "sus-7", "hom-9"}
    returned_scids = {r["source_case_id"] for r in data}
    assert returned_scids.issubset(zz_female_scids)


def test_age_range_filter(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """age_min/max filter against ZZ corpus must return cases with victims in range."""
    resp = admin_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&age_min=18&age_max=25&limit=10000"
    )
    assert resp.status_code == 200
    # hom-1 (20), hom-2 (22), hom-3 (24), sus-8 (19) should all qualify
    data = resp.json()["data"]
    assert len(data) >= 4


def test_year_range_filter(admin_client: TestClient, corpus: SeededCorpus) -> None:
    resp = admin_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&year_min=2010&year_max=2015&limit=10000"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Expect: hom-2(2010), hom-3(2012), hom-4(2015), hom-9(2011), hom-10(2013), sus-8(2014)
    assert len(data) >= 4
    for item in data:
        if item["incident_date"] is not None:
            year = int(item["incident_date"][:4])
            assert 2010 <= year <= 2015


def test_case_with_no_victim_disappears_when_demographic_filter_set(
    admin_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    """hom-6 (no victims) appears in unfiltered ZZ results but not when
    gender=Female is applied — the filter excludes cases with no victim."""
    # Must appear in the unfiltered result
    resp_all = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    assert any(item["source_case_id"] == "hom-6" for item in resp_all.json()["data"])

    # Must be absent when gender filter is applied
    resp_f = admin_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&gender=female&limit=10000"
    )
    assert not any(item["source_case_id"] == "hom-6" for item in resp_f.json()["data"])


# ---------------------------------------------------------------------------
# API contract tests (no corpus dependency — any data suffices)
# ---------------------------------------------------------------------------


def test_invalid_bbox_returns_422(admin_client: TestClient, corpus: SeededCorpus) -> None:
    bad_inputs = [
        "1,2,3",
        "1,2,3,4,5",
        "a,b,c,d",
        "-200,36,-75,40",
        "-80,95,-75,40",
        "-75,36,-80,40",
    ]
    for bbox in bad_inputs:
        resp = admin_client.get(f"/api/v1/cold-cases/map?bbox={bbox}")
        assert resp.status_code == 422, f"{bbox!r} should 422, got {resp.status_code}"


def test_limit_truncation_flag(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """Requesting limit=1 against ZZ corpus must set truncated=True."""
    resp = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["meta"]["truncated"] is True


def test_limit_over_max_returns_422(admin_client: TestClient, corpus: SeededCorpus) -> None:
    resp = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&limit=10000000")
    assert resp.status_code == 422


def test_map_without_bbox_returns_all_geocoded(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/map")
    assert r.status_code == 200
    body = r.json()
    # No zoom param → historical point mode.
    assert body["mode"] == "points"
    # Every row has non-null coordinates (geocoded filter is always applied)
    assert all(row["latitude"] is not None for row in body["data"])
    assert all(row["longitude"] is not None for row in body["data"])
    # Meta bbox is null when no bbox supplied
    assert body["meta"]["bbox"] is None


# --- Server-side cluster aggregation (low zoom) ---


def test_map_low_zoom_returns_clusters(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Below the cluster threshold the map returns aggregated grid cells,
    not individual points — the fix for silent truncation at national zoom."""
    r = public_client.get("/api/v1/cold-cases/map?zoom=4")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "clusters"
    assert body["data"] == []
    assert len(body["clusters"]) > 0
    for c in body["clusters"]:
        assert set(c.keys()) == {"latitude", "longitude", "count"}
        assert c["count"] >= 1


def test_map_clusters_account_for_every_geocoded_case(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """Cluster counts must sum to the full geocoded corpus — no case is
    dropped by aggregation, which is the whole point versus the capped
    point query."""
    r = public_client.get("/api/v1/cold-cases/map?zoom=3")
    body = r.json()
    total_in_clusters = sum(c["count"] for c in body["clusters"])
    assert total_in_clusters == body["meta"]["total_unfiltered"]
    # Aggregation never truncates.
    assert body["meta"]["truncated"] is False


def test_map_high_zoom_returns_points(public_client: TestClient, corpus: SeededCorpus) -> None:
    """At or above the cluster threshold the map returns individual points."""
    r = public_client.get(f"/api/v1/cold-cases/map?zoom=12&bbox={WORLD_BBOX}")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "points"
    assert body["clusters"] == []


def test_map_clusters_respect_filters(public_client: TestClient, corpus: SeededCorpus, corpus2: SeededCorpus) -> None:
    """A filter applied in cluster mode must shrink the aggregated total.

    Unfiltered side = ZZ + YY combined (both module corpora via source_system
    CSV), filtered side = ZZ only (state=ZZ within the same source set).
    Both totals are derived from the module's own seeded data so the assertion
    never depends on the global DB state.
    """
    unfiltered = public_client.get(
        f"/api/v1/cold-cases/map?zoom=4&bbox={WORLD_BBOX}"
        "&source_system=MAP_API_TEST,MAP_API_TEST_2"
    ).json()
    filtered = public_client.get(
        f"/api/v1/cold-cases/map?zoom=4&bbox={WORLD_BBOX}"
        "&source_system=MAP_API_TEST,MAP_API_TEST_2&state=ZZ"
    ).json()
    unfiltered_total = sum(c["count"] for c in unfiltered["clusters"])
    filtered_total = sum(c["count"] for c in filtered["clusters"])
    assert 0 < filtered_total < unfiltered_total


def test_map_no_double_count_for_multi_victim_cases(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    """Regression: previously the map query LEFT JOINed cold_case.victim, so a
    case with N victims came back as N rows. Verify hom-5 (2 victims) appears
    exactly once — then extend to the whole ZZ corpus."""
    r = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    assert r.status_code == 200
    body = r.json()
    case_ids = [row["case_id"] for row in body["data"]]
    assert len(case_ids) == len(set(case_ids)), "duplicate case_id in map response"
    # ZZ corpus must return exactly 10 cases (hom-5 has 2 victims — if de-dup
    # is broken it would appear twice)
    assert len(case_ids) == len(
        _CASES
    ), f"expected {len(_CASES)} ZZ cases, got {len(case_ids)} — multi-victim double-count?"


def test_map_without_bbox_respects_filters(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get("/api/v1/cold-cases/map?case_type=homicide&state=ZZ")
    assert r.status_code == 200
    body = r.json()
    # All returned rows match the filter
    for row in body["data"]:
        assert row["case_type"] == "homicide"
    # Must actually surface some rows from our seeded corpus
    assert any(row["state"] == "ZZ" for row in body["data"])


def test_map_item_has_slug(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) > 0
    for row in body["data"]:
        assert "slug" in row
        assert isinstance(row["slug"], str)
        assert len(row["slug"]) > 0


def test_map_item_has_victim_genders_as_list(public_client: TestClient, corpus: SeededCorpus) -> None:
    """hom-1 has gender=Female — it should appear with a non-empty victim_genders list."""
    r = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    body = r.json()
    # Find hom-1 (female, hispanic, street)
    target = next((c for c in body["data"] if c["source_case_id"] == "hom-1"), None)
    assert target is not None, "hom-1 should appear in ZZ map response"
    assert "victim_genders" in target
    assert isinstance(target["victim_genders"], list)
    assert len(target["victim_genders"]) > 0
    # Values are distinct non-null strings
    assert len(set(target["victim_genders"])) == len(target["victim_genders"])
    assert all(isinstance(g, str) for g in target["victim_genders"])


def test_map_item_has_victim_races_as_list(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Shape-only assertion — every ZZ map item has victim_races as a list."""
    r = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ")
    body = r.json()
    for row in body["data"]:
        assert "victim_races" in row
        assert isinstance(row["victim_races"], list)
        # Distinct values only
        assert len(set(row["victim_races"])) == len(row["victim_races"])


def test_map_item_has_source_case_id(public_client: TestClient, corpus: SeededCorpus) -> None:
    r = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) > 0
    for row in body["data"]:
        assert "source_case_id" in row
        assert isinstance(row["source_case_id"], str)
        assert len(row["source_case_id"]) > 0


def test_map_item_has_victim_primary_name(public_client: TestClient, corpus: SeededCorpus) -> None:
    """hom-9 has first_name='Iris', last_name='India' — primary name must be non-null."""
    r = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    body = r.json()
    target = next((c for c in body["data"] if c["source_case_id"] == "hom-9"), None)
    assert target is not None
    assert "victim_primary_name" in target
    assert target["victim_primary_name"] is not None
    assert len(target["victim_primary_name"].strip()) > 0


def test_map_item_victim_primary_name_null_for_unidentified(
    public_client: TestClient,
    corpus: SeededCorpus,
) -> None:
    """hom-10 has a victim row with first_name=None AND last_name=None —
    victim_primary_name must be null."""
    r = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    target = next((c for c in r.json()["data"] if c["source_case_id"] == "hom-10"), None)
    assert target is not None
    assert target["victim_primary_name"] is None


# ---------------------------------------------------------------------------
# Multi-value filter tests (comma-separated values → SQL ANY() membership)
# ---------------------------------------------------------------------------


def test_map_case_type_multi_value_returns_union(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?case_type=homicide,suspicious_death returns rows matching EITHER type
    and the count equals the sum of each individual filter — scoped to state=ZZ."""
    r_hom = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&case_type=homicide&limit=10000"
    )
    r_sus = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&case_type=suspicious_death&limit=10000"
    )
    r_both = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ"
        "&case_type=homicide,suspicious_death&limit=10000"
    )
    assert r_hom.status_code == 200
    assert r_sus.status_code == 200
    assert r_both.status_code == 200

    count_hom = len(r_hom.json()["data"])
    count_sus = len(r_sus.json()["data"])
    count_both = len(r_both.json()["data"])

    assert count_hom == 8
    assert count_sus == 2
    # Multi-value is the union (disjoint types)
    assert count_both == count_hom + count_sus
    assert count_both > 0

    returned_types = {r["case_type"] for r in r_both.json()["data"]}
    assert returned_types == {"homicide", "suspicious_death"}


def test_map_gender_multi_value_returns_union(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?gender=Male,Female returns rows whose victims include EITHER gender
    — scoped to ZZ so we know exactly which cases qualify."""
    r_both = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&gender=male,female&limit=10000"
    )
    assert r_both.status_code == 200
    data = r_both.json()["data"]
    # Non-empty: multi-value must surface rows (the old bug returned zero)
    assert len(data) > 0
    # hom-6 (no victims) and hom-10 (unnamed, no gender) should NOT appear
    returned_scids = {r["source_case_id"] for r in data}
    assert "hom-6" not in returned_scids
    # All cases with Male or Female victims should appear
    assert "hom-1" in returned_scids  # Female
    assert "hom-2" in returned_scids  # Male
    assert "hom-5" in returned_scids  # both genders


def test_map_race_multi_value_returns_union(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?race=White,hispanic returns rows whose victims include EITHER race."""
    r_both = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&race=White,hispanic&limit=10000"
    )
    assert r_both.status_code == 200
    data = r_both.json()["data"]
    assert len(data) > 0
    # All 3 hispanic cases + White cases should be present
    returned_scids = {r["source_case_id"] for r in data}
    assert "hom-1" in returned_scids  # hispanic
    assert "hom-2" in returned_scids  # White
    assert "hom-3" in returned_scids  # hispanic


def test_map_single_value_backward_compat(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Single-value query params still work — no regression from the multi-value refactor."""
    r = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&case_type=homicide&limit=10"
    )
    assert r.status_code == 200
    for row in r.json()["data"]:
        assert row["case_type"] == "homicide"


def test_map_whitespace_and_empty_values_skipped(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Empty / whitespace-only values don't apply a spurious filter — scoped to ZZ."""
    r1 = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&case_type=&limit=10000"
    )
    r2 = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&case_type=,,,&limit=10000"
    )
    r3 = public_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200
    # All three behave as no-filter within ZZ
    assert len(r1.json()["data"]) == len(r3.json()["data"])
    assert len(r2.json()["data"]) == len(r3.json()["data"])


def test_map_accepts_long_multivalue_race(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """Race CSV with 5 typical values (~42 chars) must NOT hit 422 on max_length."""
    long_csv = "White,Black,Hispanic,Asian,American-Indian"
    assert len(long_csv) > 32
    resp = admin_client.get(f"/api/v1/cold-cases/map?race={long_csv}")
    assert resp.status_code == 200


def test_map_accepts_long_multivalue_gender(admin_client: TestClient, corpus: SeededCorpus) -> None:
    long_csv = "Male,Female,Unknown,Nonbinary,Other"
    assert len(long_csv) > 32
    resp = admin_client.get(f"/api/v1/cold-cases/map?gender={long_csv}")
    assert resp.status_code == 200


def test_map_accepts_long_multivalue_case_type(admin_client: TestClient, corpus: SeededCorpus) -> None:
    long_csv = "homicide,missing-person,suspicious-death,unidentified-remains"
    assert len(long_csv) > 60  # case_type max_length was bumped from 64 to 256 in PR #35
    resp = admin_client.get(f"/api/v1/cold-cases/map?case_type={long_csv}")
    assert resp.status_code == 200


def test_map_meta_includes_total_unfiltered(admin_client: TestClient, corpus: SeededCorpus) -> None:
    """total_unfiltered is independent of filters; returned is filter-scoped.
    Scoped to ZZ so the counts are predictable."""
    full = admin_client.get(f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&limit=10000")
    assert full.status_code == 200
    full_body = full.json()
    assert "total_unfiltered" in full_body["meta"]
    # ZZ corpus has geocoded cases, so total_unfiltered > 0
    assert full_body["meta"]["total_unfiltered"] > 0
    zz_total = full_body["meta"]["returned"]

    # Apply gender filter — returned narrows, total_unfiltered stays the same
    filtered = admin_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&gender=female&limit=10000"
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["meta"]["total_unfiltered"] == full_body["meta"]["total_unfiltered"]
    assert body["meta"]["returned"] < zz_total


# ---------------------------------------------------------------------------
# source_system filter tests
# Scope: these tests use the seeded MAP_API_TEST source system.
# ---------------------------------------------------------------------------


def test_map_filters_by_source_system(public_client: TestClient, corpus: SeededCorpus) -> None:
    """source_system=MAP_API_TEST narrows map results vs. unfiltered baseline."""
    r_all = public_client.get("/api/v1/cold-cases/map")
    r_zz = public_client.get("/api/v1/cold-cases/map?source_system=MAP_API_TEST")
    assert r_all.status_code == 200
    assert r_zz.status_code == 200
    zz_returned = r_zz.json()["meta"]["returned"]
    assert zz_returned == len(_CASES)
    assert zz_returned < r_all.json()["meta"]["total_unfiltered"]


def test_map_filters_by_multiple_source_systems(
    public_client: TestClient, corpus: SeededCorpus, corpus2: SeededCorpus
) -> None:
    """Comma-separated source_system codes return the union of both corpora.

    Uses the module's own two synthetic sources (MAP_API_TEST / ZZ-state and
    MAP_API_TEST_2 / YY-state) so the test never depends on historical data.

    Assertions:
    - Single-source filter returns only the matching corpus (discriminates).
    - Combined filter returns exactly the sum of both corpora (union, disjoint).
    - The returned case_id set equals the union of both corpora's case_ids.
    """
    r_zz = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&source_system=MAP_API_TEST&limit=10000"
    )
    r_yy = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&source_system=MAP_API_TEST_2&limit=10000"
    )
    r_both = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}"
        "&source_system=MAP_API_TEST,MAP_API_TEST_2&limit=10000"
    )
    assert r_zz.status_code == 200
    assert r_yy.status_code == 200
    assert r_both.status_code == 200

    count_zz = r_zz.json()["meta"]["returned"]
    count_yy = r_yy.json()["meta"]["returned"]
    count_both = r_both.json()["meta"]["returned"]

    # Single-source filters return the right corpus size
    assert count_zz == len(_CASES)
    assert count_yy == len(_YY_CASES)

    # Combined filter is the exact union (sources are disjoint)
    assert count_both == count_zz + count_yy

    # The returned case_ids equal the union of both corpora
    both_ids = {row["case_id"] for row in r_both.json()["data"]}
    expected_ids = set(corpus.case_ids.values()) | set(corpus2.case_ids.values())
    assert both_ids == expected_ids


def test_map_source_system_narrows_vs_unfiltered(public_client: TestClient, corpus: SeededCorpus) -> None:
    """A single-source filter returns fewer geocoded rows than the full set."""
    r_all = public_client.get("/api/v1/cold-cases/map")
    r_ss = public_client.get("/api/v1/cold-cases/map?source_system=MAP_API_TEST")
    assert r_all.status_code == 200
    assert r_ss.status_code == 200
    assert r_ss.json()["meta"]["returned"] < r_all.json()["meta"]["total_unfiltered"]


def test_map_source_system_unknown_code_returns_empty(
    public_client: TestClient, corpus: SeededCorpus
) -> None:
    """An unknown source_system code matches no rows."""
    r = public_client.get("/api/v1/cold-cases/map?source_system=NONEXISTENT_SOURCE_CODE")
    assert r.status_code == 200
    assert r.json()["meta"]["returned"] == 0
    assert r.json()["data"] == []


def test_map_source_system_empty_csv_no_op(public_client: TestClient, corpus: SeededCorpus) -> None:
    """Empty source_system param is a no-op (matches _split_csv behavior)."""
    r_all = public_client.get("/api/v1/cold-cases/map?state=ZZ&limit=10000")
    r_empty = public_client.get("/api/v1/cold-cases/map?source_system=&state=ZZ&limit=10000")
    assert r_all.status_code == 200
    assert r_empty.status_code == 200
    assert r_empty.json()["meta"]["returned"] == r_all.json()["meta"]["returned"]


# ---------------------------------------------------------------------------
# Precision filter tests
# ---------------------------------------------------------------------------


def test_map_precision_filter_single(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?precision=street scoped to ZZ returns only street-precision cases."""
    r = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&precision=street&limit=10000"
    )
    assert r.status_code == 200
    data = r.json()["data"]
    # ZZ corpus: hom-1, hom-3, hom-5, sus-7, hom-9 are street-precision (5 cases)
    assert len(data) == 5
    for item in data:
        assert item.get("geocode_precision") == "street"


def test_map_precision_filter_multi(public_client: TestClient, corpus: SeededCorpus) -> None:
    """?precision=street,landmark scoped to ZZ returns union of both tiers."""
    r = public_client.get(
        f"/api/v1/cold-cases/map?bbox={WORLD_BBOX}&state=ZZ&precision=street,landmark&limit=10000"
    )
    assert r.status_code == 200
    data = r.json()["data"]
    # ZZ corpus: all 10 cases have either street or landmark precision
    assert len(data) == len(_CASES)
    for item in data:
        assert item.get("geocode_precision") in ("street", "landmark")
