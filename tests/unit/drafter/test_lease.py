import json
from pathlib import Path

import pytest

from casesignal.drafter import lease


def test_acquire_writes_a_readable_lease(tmp_path: Path) -> None:
    held = lease.acquire(tmp_path, "cold_case_ok_osbi", "feat/cold_case_ok_osbi-draft")
    assert held.adapter_name == "cold_case_ok_osbi"
    assert held.branch == "feat/cold_case_ok_osbi-draft"
    assert (tmp_path / "lease.json").exists()
    assert lease.read(tmp_path) == held
    # The write goes through a temp path and os.replace; nothing is left beside it.
    assert sorted(p.name for p in tmp_path.iterdir()) == [".lease.lock", "lease.json"]


def test_second_acquire_refuses_and_names_the_holder(tmp_path: Path) -> None:
    first = lease.acquire(tmp_path, "cold_case_ok_osbi", "b1")
    with pytest.raises(lease.LeaseHeld) as exc:
        lease.acquire(tmp_path, "cold_case_ok_osbi", "b2")
    assert exc.value.lease.pid == first.pid
    # Task 15 surfaces this message verbatim, so the whole contract is asserted.
    message = str(exc.value)
    assert str(first.pid) in message
    assert first.host in message
    assert f"branch {first.branch}" in message
    assert "--force" in message


def test_force_breaks_an_existing_lease(tmp_path: Path) -> None:
    lease.acquire(tmp_path, "cold_case_ok_osbi", "b1")
    forced = lease.acquire(tmp_path, "cold_case_ok_osbi", "b2", force=True)
    assert forced.branch == "b2"


def test_release_allows_a_fresh_acquire(tmp_path: Path) -> None:
    lease.acquire(tmp_path, "cold_case_ok_osbi", "b1")
    lease.release(tmp_path)
    assert lease.read(tmp_path) is None
    assert lease.acquire(tmp_path, "cold_case_ok_osbi", "b2").branch == "b2"


def test_release_is_idempotent(tmp_path: Path) -> None:
    lease.release(tmp_path)
    lease.release(tmp_path)


def test_acquire_creates_a_missing_draft_dir(tmp_path: Path) -> None:
    nested = tmp_path / "drafts" / "cold_case_ok_osbi"
    held = lease.acquire(nested, "cold_case_ok_osbi", "b1")
    assert (nested / "lease.json").exists()
    assert lease.read(nested) == held


def test_truncated_lease_is_treated_as_absent(tmp_path: Path) -> None:
    # A run SIGKILLed mid-write leaves a zero-length file; --force must still work,
    # so a lease that cannot be parsed must read as no lease at all.
    (tmp_path / "lease.json").write_text("")
    assert lease.read(tmp_path) is None
    assert lease.acquire(tmp_path, "cold_case_ok_osbi", "b2").branch == "b2"


def test_lease_missing_a_required_field_is_treated_as_absent(tmp_path: Path) -> None:
    # Schema drift: a lease.json written before Lease gained a field must not crash.
    (tmp_path / "lease.json").write_text(json.dumps({"adapter_name": "cold_case_ok_osbi"}))
    assert lease.read(tmp_path) is None
    assert lease.acquire(tmp_path, "cold_case_ok_osbi", "b2").branch == "b2"


def test_only_one_concurrent_claim_wins(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(4)

    def claim(index: int) -> bool:
        barrier.wait()
        try:
            lease.acquire(tmp_path, "example", f"draft/{index}")
        except lease.LeaseHeld:
            return False
        return True

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(4))) == 1
