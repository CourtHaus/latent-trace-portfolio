from casesignal.scout.discovery.ingest_results import candidates_from_results
from casesignal.scout.models import Channel, Status


def test_ingest_dedups_and_sets_candidate_status() -> None:
    seen: set[str] = set()
    results = [
        {"state": "TX", "level": "state", "url": "https://a.gov/coldcases"},
        {"state": "TX", "level": "state", "url": "https://a.gov/coldcases?page=2"},  # dup path prefix
        {"state": "TX", "level": "county", "url": "https://b.gov/sheriff", "county": "Harris"},
    ]
    cands = candidates_from_results(results, seen)
    assert len(cands) == 2
    assert all(c.status == Status.CANDIDATE and c.channel == Channel.WEB for c in cands)
    assert {c.county for c in cands} == {None, "Harris"}
