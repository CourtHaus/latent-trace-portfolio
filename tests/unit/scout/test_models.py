# tests/unit/scout/test_models.py
from casesignal.scout.models import Channel, dedup_key


def test_dedup_key_prefers_dataset_id() -> None:
    assert dedup_key(Channel.SOCRATA, "abcd-1234", "https://data.x.gov/d/abcd-1234") == "abcd-1234"


def test_dedup_key_falls_back_to_host_and_path_prefix() -> None:
    # Same host, different agency path prefixes must NOT collapse.
    a = dedup_key(Channel.WEB, None, "https://portal.state.gov/dps/coldcases?area=A")
    b = dedup_key(Channel.WEB, None, "https://portal.state.gov/sheriff/coldcases")
    assert a != b
    # Trailing query/fragment on the same path prefix collapse to one key.
    c = dedup_key(Channel.WEB, None, "https://portal.state.gov/dps/coldcases?area=B#x")
    assert a == c
