from pathlib import Path

from casesignal.scout.models import Candidate, Channel, Level, Status
from casesignal.scout.registry import Registry, covered_states


def _cand(cid: str, status: Status = Status.CANDIDATE) -> Candidate:
    return Candidate(id=cid, level=Level.STATE, state="TX",
                     index_url="https://x.gov/a", channel=Channel.WEB, status=status)


def test_roundtrip_and_upsert(tmp_path: Path) -> None:
    reg = Registry.load(tmp_path / "registry.yaml")
    reg.upsert(_cand("tx_dps"))
    reg.save(tmp_path / "registry.yaml")
    again = Registry.load(tmp_path / "registry.yaml")
    got = again.get("tx_dps")
    assert got is not None
    assert got.state == "TX"


def test_upsert_does_not_regress_terminal_status(tmp_path: Path) -> None:
    reg = Registry.load(tmp_path / "registry.yaml")
    reg.upsert(_cand("tx_dps", Status.ACCEPTED))
    reg.upsert(_cand("tx_dps", Status.CANDIDATE))  # a re-discovery must not undo acceptance
    got = reg.get("tx_dps")
    assert got is not None
    assert got.status == Status.ACCEPTED


def test_deferred_ledger(tmp_path: Path) -> None:
    reg = Registry.load(tmp_path / "registry.yaml")
    reg.defer_county("TX", "Loving", 254, "dry streak reached")
    assert reg.deferred()[0]["county"] == "Loving"


def test_covered_states_from_source_filenames(tmp_path: Path) -> None:
    (tmp_path / "cold_case_ok.yaml").write_text("x: 1\n")
    (tmp_path / "cold_case_ar.yaml").write_text("x: 1\n")
    (tmp_path / "not_a_source.yaml").write_text("x: 1\n")
    assert covered_states(tmp_path) == {"OK", "AR"}
