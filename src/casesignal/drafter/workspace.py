"""Isolated git worktree for the parser pass — the drafter's containment boundary.

The drafting agent is pointed at the worktree, never at the operator's checkout,
so a bad write lands in a throwaway tree. ``apply_back`` is the gate on the way
home: it copies only regular files under the allowlisted prefixes, to destinations
no symlink can redirect, and refuses the whole round otherwise. Because the write
happened in a checkout we are about to throw away, a refusal needs no restoration
— the bad file is simply never copied.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Porcelain status letters for a rename or a copy. In ``-z`` mode these entries
# carry a second, separately NUL-terminated field holding the pre-rename path.
_RENAME_CODES = frozenset("RC")


@dataclass(frozen=True)
class Workspace:
    """A throwaway checkout of ``repo_root`` on its own branch."""

    branch: str
    path: Path
    repo_root: Path


class DisallowedWrite(Exception):
    """Raised when apply-back refuses to copy what the draft did back to the repo."""

    _reason = "wrote outside the allowed paths"

    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        super().__init__(f"draft {self._reason}: {', '.join(paths)}")


class DeletedInWorkspace(DisallowedWrite):
    """Raised when the draft removed a tracked file; apply-back only adds and modifies."""

    _reason = "deleted files, which apply-back does not replay"


class UnsupportedEntry(DisallowedWrite):
    """Raised for a changed path that is not a plain regular file in the worktree."""

    _reason = "produced entries that are not regular files (a symlink, or a whole directory)"


class RedirectedDestination(DisallowedWrite):
    """Raised when a symlink in the repo would send an allowlisted write somewhere else."""

    _reason = "targeted destinations a symlink redirects out of their allowlisted location"


class WorkspaceExists(Exception):
    """Raised when ``create`` would collide with an existing branch or a non-empty path."""


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        # surrogateescape mirrors os.fsdecode, so a path whose bytes are not
        # valid UTF-8 round-trips back to the same bytes when we open it.
        encoding="utf-8",
        errors="surrogateescape",
    )


def _git(cwd: Path, *args: str) -> str:
    proc = _run_git(cwd, *args)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc.stdout


def _branch_exists(repo_root: Path, branch: str) -> bool:
    return (
        _run_git(repo_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode
        == 0
    )


def _status_entries(ws: Workspace) -> list[tuple[str, str]]:
    """Return ``(XY, path)`` pairs from porcelain status, one per affected path.

    ``-z`` is not an optimisation: without it git *quotes and escapes* any path
    holding a space or a non-ASCII byte (``"case list/na\\303\\257ve.png"``), which
    silently stops matching an allowlist prefix. NUL separators mean the path is
    never quoted and never needs unescaping.

    A rename is reported by git as one entry naming the new path plus a trailing
    field naming the old one. The drafting agent has Write and Edit only and never
    stages anything, so a rename should be unreachable; if one appears anyway it is
    recorded here as a write of the new path *and* a delete of the old, which
    ``apply_back`` then refuses rather than half-applying.
    """
    out = _git(ws.path, "status", "--porcelain", "-z", "--untracked-files=all")
    fields = out.split("\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue  # the trailing NUL leaves an empty final field
        code, path = field[:2], field[3:]
        entries.append((code, path))
        if not _RENAME_CODES.isdisjoint(code) and index < len(fields):
            entries.append(("D ", fields[index]))
            index += 1
    return entries


def _resolves_inside(path: Path, root: Path) -> bool:
    """True when ``path`` stays under ``root`` once symlinked parents are resolved."""
    return root == path.resolve() or root in path.resolve().parents


def _is_redirected(rel: str, repo_root: Path) -> bool:
    """True when any component of ``repo_root/rel`` is a symlink, or the path escapes.

    ``shutil.copy2``'s ``follow_symlinks`` argument governs only the *source*: the
    destination is opened with ``open(dst, "wb")``, which follows a symlink at
    ``dst`` and writes through it. A link anywhere along the destination path is
    therefore an allowlist bypass — ``src/pkg/mod.py -> ../../.git/hooks/pre-commit``
    installs an executable hook while apply-back reports a clean allowlisted write.
    Refusing every symlinked component covers that and subsumes the escape-the-repo
    case, which cannot be reached without traversing one (git never emits ``..``).

    Precondition: ``rel`` comes from ``_status_entries``, so it is git-normalised
    and free of ``..``. That is load-bearing, not incidental — this walk resolves
    nothing, so ``src/pkg/../../pyproject.toml`` would be judged un-redirected here
    while ``_has_allowed_prefix`` judged it allowed, and the pair would let a write
    out of the allowlist. A caller feeding ``apply_back`` paths from anywhere else
    must normalise them first.
    """
    walked = repo_root
    for part in Path(rel).parts:
        walked = walked / part
        if walked.is_symlink():
            return True
    return not _resolves_inside(walked, repo_root)


def _has_allowed_prefix(path: str, allowed: Iterable[str]) -> bool:
    """True when ``path`` is one of the allowed paths, or sits under one as a directory.

    Matching is at a path boundary, not a bare string prefix: ``src/adapters/ok``
    admits ``src/adapters/ok`` and ``src/adapters/ok/x.py`` but never
    ``src/adapters/ok_EVIL/x.py``. A trailing slash on the caller's entry is
    optional, so the containment boundary no longer rests on a prose convention.
    """
    for entry in allowed:
        prefix = entry.rstrip("/")
        if not prefix:
            continue  # "" or "/" would otherwise admit the entire repository
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def changed_paths(ws: Workspace) -> list[str]:
    """Return every repo-relative path the draft added, modified, or removed, sorted."""
    return sorted({path for _code, path in _status_entries(ws)})


def stray_writes(changed: Iterable[str], allowed: Iterable[str]) -> list[str]:
    """The paths in ``changed`` that no entry in ``allowed`` admits, in the order given.

    ``apply_back`` uses this for its own allowlist gate, so a caller checking a
    round mid-run and the gate that refuses it at the end cannot answer
    differently. The drafting loop needs the answer BEFORE apply-back: a stray
    write is cumulative in a worktree that never commits, so every later round is
    spent on a draft that can no longer be brought home.
    """
    return [path for path in changed if not _has_allowed_prefix(path, allowed)]


def unsupported_entries(ws: Workspace, changed: Iterable[str]) -> list[str]:
    """The changed paths that are not plain regular files in the worktree.

    A symlink the draft wrote, or a directory git reports as one entry with a
    trailing slash (an untracked directory holding its own .git). ``apply_back``
    refuses the round for either; the drafting loop asks the same question
    mid-run, because the condition is cumulative in a tree that never commits and
    every further round is spent on a draft that can no longer come home.

    ``is_symlink`` is tested first because ``is_file`` follows links, so a symlink
    to a regular file would otherwise pass.
    """
    return [
        path for path in changed if (ws.path / path).is_symlink() or not (ws.path / path).is_file()
    ]


def redirected_destinations(ws: Workspace, changed: Iterable[str]) -> list[str]:
    """The changed paths a symlink in the repository would send somewhere else.

    Split out for the same reason as :func:`unsupported_entries`: one matcher, so
    a caller checking a round mid-run and the gate that refuses it at the end
    cannot answer differently. See :func:`_is_redirected` for what is checked and
    why a symlinked component anywhere on the destination path is an allowlist
    bypass rather than a curiosity.
    """
    repo_root = ws.repo_root.resolve()
    return [path for path in changed if _is_redirected(path, repo_root)]


def apply_back(ws: Workspace, allowed: Sequence[str]) -> list[str]:
    """Copy the draft's writes home, or refuse the whole round.

    ``allowed`` holds paths relative to the repo root, e.g.
    ``src/casesignal/etl/adapters/cold_case_ok_osbi/``. Each entry admits that
    exact path and anything beneath it; a trailing slash is optional.

    Every refusal happens before the first copy, so a rejected round leaves the
    repo untouched. A ``DeletedInWorkspace`` refusal ends the run rather than the
    round: the deletion stays in the worktree, so every later ``apply_back`` in the
    session would raise it again. Files git ignores are invisible to these checks
    and are neither reported nor copied.
    """
    entries = _status_entries(ws)
    changed = sorted({path for _code, path in entries})

    stray = stray_writes(changed, allowed)
    if stray:
        raise DisallowedWrite(stray)

    deleted = sorted({path for code, path in entries if "D" in code})
    if deleted:
        raise DeletedInWorkspace(deleted)

    sources = [(rel, ws.path / rel) for rel in changed]
    # Copying a symlink or a directory entry would raise mid-loop, after earlier
    # paths had already landed in the repo, so both are refused before any copy.
    unsupported = unsupported_entries(ws, changed)
    if unsupported:
        raise UnsupportedEntry(unsupported)

    redirected = redirected_destinations(ws, changed)
    if redirected:
        raise RedirectedDestination(redirected)

    repo_root = ws.repo_root.resolve()

    applied: list[str] = []
    for rel, src in sources:
        dest = repo_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        # follow_symlinks=False keeps a source that turned into a symlink between
        # the gate above and this copy from being dereferenced into the repo.
        shutil.copy2(src, dest, follow_symlinks=False)
        applied.append(rel)
    return applied


def create(repo_root: Path, branch: str, worktree_root: Path) -> Workspace:
    """Check ``repo_root`` out at ``worktree_root`` on a new ``branch``.

    Both collisions are pre-checked so the operator gets the real cause. git
    creates the branch *before* it lays the worktree down, so without this a
    failure on an occupied path leaves ``branch`` behind and the retry fails with
    "a branch named ... already exists" — pointing at the wrong problem entirely.
    """
    if _branch_exists(repo_root, branch):
        raise WorkspaceExists(
            f"branch {branch!r} already exists in {repo_root}; a previous draft left it "
            f"behind (destroy() keeps the branch on purpose, and a draft whose "
            f"apply-back was refused keeps its WORKTREE too). Inspect it, then: if "
            f"`git worktree list` still shows a worktree on {branch!r}, "
            f"`git worktree remove --force <that path>` FIRST -- git refuses to delete "
            f"a branch a worktree is still using -- and then `git branch -D {branch}`. "
            f"Or draft under another name."
        )
    if worktree_root.exists() and (not worktree_root.is_dir() or any(worktree_root.iterdir())):
        raise WorkspaceExists(
            f"worktree path {worktree_root} already exists and is not an empty directory; "
            f"remove it or draft somewhere else."
        )
    worktree_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(repo_root, "worktree", "add", "-b", branch, str(worktree_root))
    except RuntimeError:
        if _branch_exists(repo_root, branch):
            _run_git(repo_root, "branch", "-D", branch)  # best effort; never mask the cause
        raise
    return Workspace(branch=branch, path=worktree_root, repo_root=repo_root)


def destroy(ws: Workspace) -> None:
    """Delete the worktree, keeping its branch so the draft history stays inspectable."""
    _git(ws.repo_root, "worktree", "remove", "--force", str(ws.path))
