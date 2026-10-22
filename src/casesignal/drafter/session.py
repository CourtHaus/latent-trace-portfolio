"""Capture sessions — one coherent snapshot of a source, never two.

A capture is a slow, rate-limited crawl, so it has to survive being interrupted.
Resume is what makes that cheap: ``fetched_path`` lets a re-run skip a page it
already holds *and* find the file it landed in. But resume is scoped to a
*session*. Fixtures from two runs days apart never merge, because a per-field
inventory measured across two versions of a site describes neither of them.

The manifest, not the directory listing, is the record of what belongs to a
session. It names the directory the fixtures were written to (``fixtures_root``,
relative to the draft directory holding the manifest), and for each fixture its
path under that root, the URL and status it came from, and the sha256 of the
bytes the server actually sent. Those two halves together are what let a later
pass re-hash a fixture on disk and confirm it is still the page the floors were
derived from. The manifest is rewritten after every single fetch, so it is
written atomically — a crawl killed mid-write leaves the previous manifest
intact, never a truncated one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

_MANIFEST = "manifest.json"

# Anything outside this set is dropped when a session id is built. See _session_id.
_UNSAFE_IN_ID = re.compile(r"[^0-9A-Za-z]+")


@dataclass(frozen=True)
class FixtureRecord:
    """One captured page: where it landed, where it came from, what its bytes hashed to.

    ``path`` is relative to the session's ``fixtures_root``, which is itself
    relative to the draft directory. The manifest alone therefore locates the file.
    """

    path: str
    url: str
    status: int
    sha256: str
    fetched_at: str


@dataclass
class CaptureSession:
    """The manifest in memory.

    Not frozen: ``record`` maintains ``fixtures`` throughout a crawl. The identity
    fields are set once by ``start`` and nothing reassigns them.

    ``fixtures_root`` is where the crawl wrote its fixture files, relative to the
    draft directory (Task 7 passes ``"fx"``). Empty means the fixtures sit beside
    the manifest. It is stored so the manifest is self-locating: ``path`` on a
    record is meaningless without it.
    """

    session_id: str
    shape: str
    started_at: str
    fixtures: list[FixtureRecord] = field(default_factory=list)
    fixtures_root: str = ""


class SessionMismatch(Exception):
    """Raised when a resume asks for a session this draft directory does not hold."""


class ManifestUnreadable(Exception):
    """Raised when a manifest exists but cannot be understood.

    Deliberately louder than :func:`casesignal.drafter.lease.read`, which treats a
    damaged lease as no lease so ``--force`` can always break it. Here the
    equivalent leniency would be the bug: reading a damaged manifest as "no
    session" invites a fresh capture on top of fixtures already on disk, and the
    blend is invisible by the time anything measures it. Since the manifest is
    written atomically, a manifest we cannot parse was not damaged by us, and the
    operator needs to know before capturing anything else.
    """


def _session_id(now: str, nonce: str) -> str:
    """Fold an ISO instant and a nonce into a compact, filename-safe identifier.

    Every character outside ``[0-9A-Za-z]`` is dropped, not just ``-`` and ``:``.
    ISO-8601 is wider than the ``Z``-suffixed form: the sibling
    :mod:`casesignal.drafter.lease` builds timestamps with
    ``isoformat(timespec="seconds")``, which yields a ``+00:00`` offset, and
    fractional seconds add a ``.``. Either would otherwise end up inside an
    identifier this docstring calls filename-safe. The nonce is folded the same
    way, so the property holds for the whole id rather than for the half we
    happen to generate.
    """
    return f"{_UNSAFE_IN_ID.sub('', now)}-{_UNSAFE_IN_ID.sub('', nonce)}"


def start(
    draft_dir: Path,
    shape: str,
    *,
    now: str,
    nonce: str,
    fixtures_root: str = "",
) -> CaptureSession:
    """Begin a new capture session, replacing any manifest already in ``draft_dir``.

    ``fixtures_root`` is the directory the crawl will write fixtures into, relative
    to ``draft_dir``; it is recorded so the manifest can locate its own fixtures.
    Creating that directory is the crawl's job, not this one's.

    This is the ``--refresh`` path: it deliberately discards the previous session's
    record. Fixture files the old session left behind are not deleted and not
    inherited — they are simply no longer named by the manifest, so nothing
    downstream counts them.
    """
    session = CaptureSession(
        session_id=_session_id(now, nonce),
        shape=shape,
        started_at=now,
        fixtures_root=fixtures_root,
    )
    _save(draft_dir, session)
    return session


def load(draft_dir: Path) -> CaptureSession | None:
    """Return the session recorded in ``draft_dir``, or None when there is no manifest.

    Raises :class:`ManifestUnreadable` when a manifest is present but unparseable
    or missing fields; a manifest we cannot read is never reported as absent.
    Every key is required, including ``fixtures``: ``_save`` always writes it, so
    its absence is damage rather than an older shape.
    """
    path = draft_dir / _MANIFEST
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return CaptureSession(
            session_id=raw["session_id"],
            shape=raw["shape"],
            started_at=raw["started_at"],
            fixtures_root=raw["fixtures_root"],
            fixtures=[FixtureRecord(**f) for f in raw["fixtures"]],
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise ManifestUnreadable(
            f"capture manifest at {path} could not be read ({exc}); it does not "
            f"identify which session its fixtures belong to, so they cannot be "
            f"resumed or measured. Inspect it, or delete the draft directory and "
            f"capture again."
        ) from exc


def resume(draft_dir: Path, session_id: str) -> CaptureSession:
    """Return the session in ``draft_dir``, refusing unless it is ``session_id``."""
    existing = load(draft_dir)
    if existing is None:
        raise SessionMismatch(f"no capture session on disk to resume as {session_id}")
    if existing.session_id != session_id:
        raise SessionMismatch(
            f"capture session on disk is {existing.session_id}, cannot resume as "
            f"{session_id}; pass --refresh to start a new session"
        )
    return existing


def fetched_path(session: CaptureSession, url: str) -> str | None:
    """Return the path this session already captured ``url`` to, or None.

    Skipping a URL on resume is only half the answer; the other half is *which
    file* holds it. A resumed run can assign a different name to the same page —
    a wider ``--detail-sample`` reshuffles the sampler, so a URL captured last run
    as ``detail_3.html`` would be handed ``detail_7.html`` this run. A caller that
    only asked "already fetched?" would then read the name it just invented and
    either miss the file or, worse, pair this URL's record key with another page's
    HTML: a mis-measured inventory produced by the resume path itself. Callers must
    read the path this returns, not the one they were about to use.
    """
    for fixture in session.fixtures:
        if fixture.url == url:
            return fixture.path
    return None


def already_fetched(session: CaptureSession, url: str) -> bool:
    """True when ``url`` was captured in this session, so the fixture on disk stands.

    A thin wrapper over :func:`fetched_path` so the two can never disagree about
    what "already fetched" means.
    """
    return fetched_path(session, url) is not None


def record(
    session: CaptureSession,
    draft_dir: Path,
    *,
    path: str,
    url: str,
    status: int,
    body: bytes,
    fetched_at: str = "",
) -> FixtureRecord:
    """Record one fetched page in ``session`` and rewrite the manifest.

    One record per URL per session. Recording a URL the session already holds
    replaces the earlier record in place, keeping its position: a retried 502 is
    superseded by the response that finally arrived, and a double call cannot
    double-count a page into the coverage floors derived from this manifest. That
    invariant belongs to the manifest, which this module owns, not to the crawl
    loop that happens to be its only caller.

    ``path`` is relative to ``session.fixtures_root``. ``body`` is the response
    bytes, and those are what get hashed. The fixture is never read back off disk
    to hash it: a global ``core.autocrlf=true`` (the default on at least one dev
    box here) rewrites line endings on checkout, so a disk-derived digest would
    stop meaning "what the server sent".
    """
    rec = FixtureRecord(
        path=path,
        url=url,
        status=status,
        sha256=hashlib.sha256(body).hexdigest(),
        fetched_at=fetched_at or session.started_at,
    )
    for index, previous in enumerate(session.fixtures):
        if previous.url == url:
            session.fixtures[index] = rec
            break
    else:
        session.fixtures.append(rec)
    _save(draft_dir, session)
    return rec


def keep_only(
    session: CaptureSession,
    draft_dir: Path,
    *,
    urls: Iterable[str],
) -> list[FixtureRecord]:
    """Narrow the manifest to ``urls``, returning the records that were dropped.

    A resume is not always a continuation of the same corpus: a site that lost a
    listing page between runs leaves this session holding a fixture for a URL the
    crawl no longer reaches. Left in the manifest, that fixture is still a page a
    later pass will re-hash and re-parse, so the count it derives exceeds the count
    the capture reported — the manifest would describe a corpus no single walk ever
    saw. Which URLs still belong is the crawl's knowledge, not this module's, so the
    crawl names them and the manifest is trimmed to match.

    The fixture files themselves are left on disk, exactly as ``start`` leaves the
    previous session's. Nothing downstream counts a file the manifest does not name.
    """
    keep = set(urls)
    kept = [fixture for fixture in session.fixtures if fixture.url in keep]
    if len(kept) == len(session.fixtures):
        return []
    dropped = [fixture for fixture in session.fixtures if fixture.url not in keep]
    session.fixtures = kept
    _save(draft_dir, session)
    return dropped


def _save(draft_dir: Path, session: CaptureSession) -> None:
    """Write the manifest atomically, so an interrupted crawl never truncates it."""
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / _MANIFEST
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(session), indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic: the previous manifest stands until this lands
