"""Fixture files a capture holds, and the rules that keep them trustworthy.

Every shape capture does the same three things with the bytes a server sent:
writes them to a file, records that file in the session manifest, and reads it
back on the next run instead of spending another rate-limited request. What
makes that safe is not transport-specific, so it lives here rather than being
restated — and eventually drifting — once per shape.

*Fixtures stay inside the fixture directory.* The names a capture generates are
counter-derived and cannot escape, but the paths it *reads* on resume come out
of the manifest, which :mod:`casesignal.drafter.session` stores verbatim and
validates not at all. A manifest carrying ``../../etc/passwd`` would otherwise
be an arbitrary read that lands in a captured record's payload. Containment is
a path-component walk after resolution, not a string prefix: ``fx/../fxevil``
starts with the fixture root's own characters and is still outside it.

*A resumed page is the page it claims to be.* The path comes from the manifest,
never from the name this run would have invented — a re-run with different
tuning reshuffles the counter, so the invented name may belong to another page
entirely. The file's bytes are then checked against the digest the manifest
recorded for that URL, because a fixture altered between runs (a checkout under
``core.autocrlf``, an editor, a partial restore) is exactly what the digest
exists to catch, and measuring bytes nobody verified is the thing it exists to
prevent.

*Fixtures land where the manifest says they do.* The manifest locates its own
files by ``fixtures_root``, fixed at ``start``. Writing them somewhere else
produces a manifest whose self-locating claim is false, and nothing notices
until a much later pass cannot find a fixture it needs to re-hash.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from casesignal.drafter import session as session_mod
from casesignal.drafter.session import CaptureSession
from casesignal.drafter.shapes.base import HttpClient

_logger = logging.getLogger(__name__)


class UnsafeFixturePath(Exception):
    """Raised when a fixture path would read or write outside the fixture directory."""


class FixtureRootMismatch(Exception):
    """Raised when the fixture directory is not the one the session recorded."""


def check_fixture_root(session: CaptureSession, draft_dir: Path, out_dir: Path) -> None:
    """Refuse a fixture directory the manifest will not be able to point at."""
    declared = (draft_dir / session.fixtures_root).resolve()
    if out_dir.resolve() != declared:
        raise FixtureRootMismatch(
            f"session {session.session_id} records fixtures_root "
            f"{session.fixtures_root!r} ({declared}), but this capture would write "
            f"to {out_dir.resolve()}; the manifest could not locate its own fixtures"
        )


def fixture_path(out_dir: Path, name: str) -> Path:
    """Resolve ``name`` under ``out_dir``, refusing anything that leaves it.

    Resolution happens before the check so a traversal segment, an absolute path,
    or a symlinked fixture is measured by where it actually lands.
    """
    root = out_dir.resolve()
    path = (root / name).resolve()
    if path != root and root not in path.parents:
        raise UnsafeFixturePath(
            f"fixture path {name!r} resolves to {path}, outside the fixture "
            f"directory {root}; refusing to read or write it"
        )
    return path


def fixture_name(
    session: CaptureSession,
    prefix: str,
    ordinal: int,
    url: str,
    *,
    suffix: str,
) -> str:
    """A fixture name for ``url`` that no other URL in this session already holds.

    Counter-derived on purpose: a name built from anything the server supplied —
    a dataset id, a layer name, a slug out of a URL — is a path the server chose.

    Ordinals normally land on a free name first try. They can collide on a resume
    where the source itself changed: the corpus is a page shorter, so this run's
    ``page_2`` is the name last run gave a page that is still in the manifest under
    a different URL. Writing there would leave that record pointing at bytes it
    does not hash to, which is exactly the corruption the manifest's sha256 exists
    to make visible. Stepping past the name costs one fixture file.
    """
    while True:
        name = f"{prefix}_{ordinal}{suffix}"
        holder = _url_holding(session, name)
        if holder is None or holder == url:
            return name
        ordinal += 1


def fetch(
    client: HttpClient,
    session: CaptureSession,
    draft_dir: Path,
    out_dir: Path,
    url: str,
    name: str,
) -> tuple[str, str]:
    """Return the fixture path ``url`` lives at and the body itself.

    The resumed path is read from the name the *manifest* recorded, never from
    ``name``: a re-run with different tuning reshuffles the counter, so ``name``
    may belong to a different page entirely. It is also the path handed back, so
    the result names files that exist rather than the name this run would have
    chosen. A recorded path whose file has since been deleted is not a fixture
    this session holds, so it is fetched again and re-recorded rather than
    reported as captured. So is one whose bytes no longer hash to what the
    manifest recorded.
    """
    recorded = session_mod.fetched_path(session, url)
    if recorded is not None:
        path = fixture_path(out_dir, recorded)
        if path.is_file():
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() == recorded_digest(session, url):
                return recorded, decode(raw)
            _logger.warning(
                "fixture %s for %s no longer matches the digest the manifest "
                "recorded for it; re-fetching. If this repeats across a whole "
                "resume, something rewrote the fixture directory (a checkout under "
                "core.autocrlf, an editor, a partial restore) and the entire source "
                "is being crawled again.",
                recorded,
                url,
            )

    response = client.get(url)
    body = response.content
    fixture_path(out_dir, name).write_bytes(body)
    session_mod.record(
        session, draft_dir, path=name, url=url, status=response.status_code, body=body
    )
    return name, decode(body)


def recorded_digest(session: CaptureSession, url: str) -> str | None:
    """The sha256 the manifest holds for ``url``, or None when it holds no record."""
    for fixture in session.fixtures:
        if fixture.url == url:
            return fixture.sha256
    return None


def decode(raw: bytes) -> str:
    """Decode response bytes the same way whether they came off the wire or off disk.

    Deliberately not ``response.text``: that path exists only on a fresh fetch, so
    using it would let a resumed capture disagree with the run it resumed about
    what a page says. UTF-8 first, then cp1252 (the practical fallback for older
    state pages), then UTF-8 with replacement so a capture is never lost to one
    stray byte.
    """
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _url_holding(session: CaptureSession, name: str) -> str | None:
    """The URL this session recorded at fixture path ``name``, if any."""
    for fixture in session.fixtures:
        if fixture.path == name:
            return fixture.url
    return None
