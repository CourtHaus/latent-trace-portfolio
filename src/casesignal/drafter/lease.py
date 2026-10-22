"""The drafting lease — one draft per adapter at a time on this machine."""

from __future__ import annotations

import fcntl
import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_LEASE_FILE = "lease.json"


@dataclass(frozen=True)
class Lease:
    adapter_name: str
    pid: int
    host: str
    created_at: str
    branch: str


class LeaseHeld(Exception):
    """Raised when a draft directory is already leased by another run."""

    def __init__(self, held: Lease) -> None:
        self.lease = held
        super().__init__(
            f"draft lease for {held.adapter_name} is held by pid {held.pid} on "
            f"{held.host} since {held.created_at} (branch {held.branch}); "
            f"pass --force to break it"
        )


def read(draft_dir: Path) -> Lease | None:
    """Return the lease held on ``draft_dir``, or None when none is readable.

    A truncated file (a run killed mid-write) or one whose fields no longer match
    ``Lease`` counts as absent rather than an error: ``--force`` is the documented
    escape hatch, so it must never be blocked by the very file it exists to break.

    Do not unify this with :func:`casesignal.drafter.session.load`, which refuses a
    damaged manifest instead of reporting it absent. The asymmetry is deliberate:
    reading a damaged lease leniently at worst breaks a lease the operator asked to
    break, while reading a damaged manifest leniently invites a fresh capture on top
    of fixtures already on disk, and that blend is invisible by the time anything
    measures it.
    """
    path = draft_dir / _LEASE_FILE
    if not path.exists():
        return None
    try:
        return Lease(**json.loads(path.read_text()))
    except (ValueError, TypeError):
        return None


def _acquire(draft_dir: Path, adapter_name: str, branch: str, *, force: bool = False) -> Lease:
    """Claim ``draft_dir`` for this process, refusing unless ``force`` breaks a live lease."""
    existing = read(draft_dir)
    if existing is not None and not force:
        raise LeaseHeld(existing)
    held = Lease(
        adapter_name=adapter_name,
        pid=os.getpid(),
        host=socket.gethostname(),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        branch=branch,
    )
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / _LEASE_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(held), indent=2))
    os.replace(tmp, path)  # atomic: never leaves a half-written lease behind
    return held


def release(draft_dir: Path) -> None:
    """Drop any lease on ``draft_dir``; a no-op when none is held."""
    (draft_dir / _LEASE_FILE).unlink(missing_ok=True)


def acquire(draft_dir: Path, adapter_name: str, branch: str, *, force: bool = False) -> Lease:
    """Serialize the check/write transaction; atomic rename alone is not a lock."""
    draft_dir.mkdir(parents=True, exist_ok=True)
    with (draft_dir / ".lease.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _acquire(draft_dir, adapter_name, branch, force=force)
