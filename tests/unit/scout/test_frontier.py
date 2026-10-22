from casesignal.scout.frontier import CountyTarget, county_cascade, state_frontier


def test_state_frontier_excludes_covered() -> None:
    targets = state_frontier(covered={"OK", "AR"}, all_states=["OK", "AR", "TX", "NM"])
    assert [t.state for t in targets] == ["TX", "NM"]
    assert "dps" in targets[0].agency_types


def _counties(n: int) -> list[CountyTarget]:
    return [CountyTarget("TX", f"C{i}", population_rank=i) for i in range(1, n + 1)]


def test_cascade_scouts_floor_even_when_all_dry() -> None:
    counties = _counties(20)
    to_scout, deferred = county_cascade(counties, has_official=lambda c: False, floor=10, dry_stop=5)
    assert len(to_scout) == 10               # floor always scouted
    assert len(deferred) == 10               # rest deferred, not dropped
    assert deferred[0].county == "C11"


def test_cascade_extends_while_hits_then_stops_after_dry_streak() -> None:
    counties = _counties(30)
    # Past the floor (C11+): C11 hits, then C12..C16 dry (5 in a row) -> stop after C16.
    hits = {"C11"}
    to_scout, deferred = county_cascade(
        counties, has_official=lambda c: c.county in hits, floor=10, dry_stop=5
    )
    scouted = {c.county for c in to_scout}
    assert "C11" in scouted and "C16" in scouted   # streak counted through C16
    assert "C17" not in scouted                    # stopped
    assert any(c.county == "C17" for c in deferred)
