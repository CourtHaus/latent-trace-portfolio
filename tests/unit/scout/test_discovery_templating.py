from casesignal.scout.discovery.templating import queries_for_county, queries_for_state
from casesignal.scout.frontier import CountyTarget, StateTarget


def test_state_queries_cover_agency_types() -> None:
    qs = queries_for_state(StateTarget("TX"))
    joined = " ".join(qs).lower()
    assert "texas" in joined
    assert "bureau of investigation" in joined and "cold case" in joined


def test_county_queries_name_county_and_state() -> None:
    qs = queries_for_county(CountyTarget("TX", "Harris", 1))
    joined = " ".join(qs).lower()
    assert "harris county" in joined and "sheriff" in joined
