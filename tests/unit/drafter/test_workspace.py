import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from casesignal.drafter import workspace


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    # A global core.autocrlf=true (the Windows/WSL default, and set on at least
    # one dev box here) checks "seed\n" back out of the worktree as "seed\r\n".
    # Path.read_text() hides that behind universal newlines, so no assertion here
    # catches it -- pin it off anyway so the fixture's bytes are what they look like.
    _git(root, "config", "core.autocrlf", "false")
    # A developer's global ignore file (core.excludesFile) is equally in play: a
    # global "*.png" makes the non-ASCII test below see no change at all.
    _git(root, "config", "core.excludesFile", "/dev/null")
    (root / "seed.txt").write_text("seed\n")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def test_create_makes_an_isolated_checkout_on_a_new_branch(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    assert ws.path.is_dir()
    assert (ws.path / "seed.txt").read_text() == "seed\n"
    assert ws.path != repo


def test_workspace_is_a_frozen_record_of_its_three_fields(tmp_path: Path) -> None:
    # Task 13 constructs a Workspace directly rather than through create().
    ws = workspace.Workspace(branch="b", path=tmp_path, repo_root=tmp_path)
    assert (ws.branch, ws.path, ws.repo_root) == ("b", tmp_path, tmp_path)
    with pytest.raises(FrozenInstanceError):
        ws.branch = "other"  # type: ignore[misc]


def test_changed_paths_reports_writes_in_the_worktree_only(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "new.txt").write_text("hi\n")
    assert workspace.changed_paths(ws) == ["new.txt"]
    assert not (repo / "new.txt").exists()


def test_apply_back_moves_allowlisted_paths_into_the_repo(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    target = ws.path / "src" / "pkg"
    target.mkdir(parents=True)
    (target / "mod.py").write_text("x = 1\n")

    applied = workspace.apply_back(ws, ["src/pkg/"])

    assert applied == ["src/pkg/mod.py"]
    assert (repo / "src" / "pkg" / "mod.py").read_text() == "x = 1\n"


def test_apply_back_refuses_writes_outside_the_allowlist(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "elsewhere.py").write_text("boom\n")

    with pytest.raises(workspace.DisallowedWrite) as exc:
        workspace.apply_back(ws, ["src/pkg/"])

    assert exc.value.paths == ["elsewhere.py"]
    assert not (repo / "elsewhere.py").exists()


def test_apply_back_copies_nothing_when_one_write_is_disallowed(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    target = ws.path / "src" / "pkg"
    target.mkdir(parents=True)
    (target / "mod.py").write_text("x = 1\n")
    (ws.path / "elsewhere.py").write_text("boom\n")

    with pytest.raises(workspace.DisallowedWrite) as exc:
        workspace.apply_back(ws, ["src/pkg/"])

    # The refusal is all-or-nothing: the allowlisted sibling stays behind too.
    assert exc.value.paths == ["elsewhere.py"]
    assert not (repo / "src").exists()


def test_changed_paths_does_not_quote_spaces_or_non_ascii(repo: Path, tmp_path: Path) -> None:
    # `git status --porcelain` (without -z) renders this path as
    # "\"case list/na\\303\\257ve img.png\"" -- quoted, escaped, and no longer a
    # prefix match for the allowlist. -z hands back the raw bytes instead.
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "case list").mkdir()
    (ws.path / "case list" / "naïve img.png").write_bytes(b"png")

    assert workspace.changed_paths(ws) == ["case list/naïve img.png"]

    applied = workspace.apply_back(ws, ["case list/"])

    assert applied == ["case list/naïve img.png"]
    assert (repo / "case list" / "naïve img.png").read_bytes() == b"png"


def test_changed_paths_parses_a_rename_without_the_arrow(repo: Path, tmp_path: Path) -> None:
    # Porcelain renders a staged rename as `R  old -> new`; the arrow must never
    # end up inside a path. Both sides of the rename are reported.
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    _git(ws.path, "mv", "seed.txt", "renamed.txt")

    assert workspace.changed_paths(ws) == ["renamed.txt", "seed.txt"]


def test_apply_back_refuses_a_rename(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    _git(ws.path, "mv", "seed.txt", "renamed.txt")

    with pytest.raises(workspace.DeletedInWorkspace) as exc:
        workspace.apply_back(ws, ["renamed.txt", "seed.txt"])

    assert exc.value.paths == ["seed.txt"]
    assert (repo / "seed.txt").read_text() == "seed\n"
    assert not (repo / "renamed.txt").exists()


def test_apply_back_refuses_a_deletion(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "seed.txt").unlink()

    with pytest.raises(workspace.DeletedInWorkspace) as exc:
        workspace.apply_back(ws, ["seed.txt"])

    assert exc.value.paths == ["seed.txt"]
    # A DeletedInWorkspace is still a DisallowedWrite, so Task 14's handler
    # catches it without knowing the subclass.
    assert isinstance(exc.value, workspace.DisallowedWrite)
    assert (repo / "seed.txt").read_text() == "seed\n"


def test_apply_back_refuses_a_destination_that_escapes_the_repo(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "pkg").symlink_to(outside, target_is_directory=True)

    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    target = ws.path / "src" / "pkg"
    target.mkdir(parents=True)
    (target / "mod.py").write_text("x = 1\n")

    with pytest.raises(workspace.RedirectedDestination) as exc:
        workspace.apply_back(ws, ["src/pkg/"])

    assert exc.value.paths == ["src/pkg/mod.py"]
    assert not (outside / "mod.py").exists()


def test_destroy_removes_the_worktree(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    workspace.destroy(ws)
    assert not ws.path.exists()


def test_apply_back_refuses_a_symlink_the_draft_wrote(repo: Path, tmp_path: Path) -> None:
    # Round 1 of the write-through chain: the draft plants a link inside the
    # allowlist. If it were copied home, round 2 would write *through* it.
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "src" / "pkg").mkdir(parents=True)
    (ws.path / "src" / "pkg" / "mod.py").symlink_to("../../seed.txt")

    with pytest.raises(workspace.UnsupportedEntry) as exc:
        workspace.apply_back(ws, ["src/pkg/"])

    assert exc.value.paths == ["src/pkg/mod.py"]
    assert not (repo / "src").exists()

    # Round 2: the draft replaces the link with a regular file. With the link
    # never planted, the destination is an ordinary new path and seed.txt lives.
    (ws.path / "src" / "pkg" / "mod.py").unlink()
    (ws.path / "src" / "pkg" / "mod.py").write_text("OWNED\n")

    assert workspace.apply_back(ws, ["src/pkg/"]) == ["src/pkg/mod.py"]
    assert (repo / "seed.txt").read_text() == "seed\n"
    assert (repo / "src" / "pkg" / "mod.py").read_text() == "OWNED\n"


def test_apply_back_refuses_writing_through_a_symlink_into_git_hooks(
    repo: Path, tmp_path: Path
) -> None:
    # shutil.copy2's follow_symlinks governs the source only; the destination is
    # opened with open(dst, "wb"), which follows a link at dst. An allowlisted
    # path pointing at .git/hooks/pre-commit is arbitrary code execution on the
    # operator's next commit, reported as a clean apply.
    hook = repo / ".git" / "hooks" / "pre-commit"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "mod.py").symlink_to(hook)

    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "src" / "pkg").mkdir(parents=True)
    (ws.path / "src" / "pkg" / "mod.py").write_text("#!/bin/sh\necho pwned\n")

    with pytest.raises(workspace.RedirectedDestination) as exc:
        workspace.apply_back(ws, ["src/pkg/"])

    assert exc.value.paths == ["src/pkg/mod.py"]
    assert not hook.exists()


def test_apply_back_refuses_a_directory_entry_before_copying_anything(
    repo: Path, tmp_path: Path
) -> None:
    # -uall reports an untracked directory that holds its own .git as a single
    # entry with a trailing slash. Copying it raises IsADirectoryError mid-loop,
    # after the alphabetically earlier sibling has already landed in the repo.
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "src" / "pkg").mkdir(parents=True)
    (ws.path / "src" / "pkg" / "aaa.py").write_text("a\n")
    nested = ws.path / "src" / "pkg" / "zzz_nested"
    nested.mkdir()
    _git(nested, "init", "-q")

    assert workspace.changed_paths(ws) == ["src/pkg/aaa.py", "src/pkg/zzz_nested/"]

    with pytest.raises(workspace.UnsupportedEntry) as exc:
        workspace.apply_back(ws, ["src/pkg/"])

    assert exc.value.paths == ["src/pkg/zzz_nested/"]
    assert not (repo / "src").exists()


def test_apply_back_matches_the_allowlist_at_a_path_boundary(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "src" / "adapters" / "ok_EVIL").mkdir(parents=True)
    (ws.path / "src" / "adapters" / "ok_EVIL" / "x.py").write_text("evil\n")

    # A sibling directory sharing the prefix is refused with or without the
    # caller's trailing slash: the boundary is not a prose convention.
    for allowed in (["src/adapters/ok/"], ["src/adapters/ok"]):
        with pytest.raises(workspace.DisallowedWrite) as exc:
            workspace.apply_back(ws, allowed)
        assert exc.value.paths == ["src/adapters/ok_EVIL/x.py"]

    # An empty entry admits nothing, rather than str.startswith("") admitting all.
    with pytest.raises(workspace.DisallowedWrite):
        workspace.apply_back(ws, [""])

    assert not (repo / "src").exists()


def test_apply_back_admits_the_allowlisted_directory_either_way(repo: Path, tmp_path: Path) -> None:
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "src" / "adapters" / "ok").mkdir(parents=True)
    (ws.path / "src" / "adapters" / "ok" / "x.py").write_text("good\n")

    assert workspace.apply_back(ws, ["src/adapters/ok"]) == ["src/adapters/ok/x.py"]
    assert (repo / "src" / "adapters" / "ok" / "x.py").read_text() == "good\n"


def test_create_refuses_a_branch_that_already_exists(repo: Path, tmp_path: Path) -> None:
    workspace.create(repo, "feat/x-draft", tmp_path / "wt")

    with pytest.raises(workspace.WorkspaceExists) as exc:
        workspace.create(repo, "feat/x-draft", tmp_path / "wt2")

    assert "feat/x-draft" in str(exc.value)
    assert "git branch -D" in str(exc.value)


def test_create_refuses_an_occupied_path_without_leaking_the_branch(
    repo: Path, tmp_path: Path
) -> None:
    occupied = tmp_path / "wt"
    occupied.mkdir()
    (occupied / "junk").write_text("x\n")

    with pytest.raises(workspace.WorkspaceExists) as exc:
        workspace.create(repo, "feat/x-draft", occupied)

    assert str(occupied) in str(exc.value)
    # The retry must report its own cause, not "a branch named ... already exists".
    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt2")
    assert ws.path.is_dir()


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores the read-only parent"
)
def test_create_deletes_the_branch_it_caused_when_git_fails(repo: Path, tmp_path: Path) -> None:
    # A failure git hits *after* creating the branch, past both pre-checks.
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        with pytest.raises(RuntimeError):
            workspace.create(repo, "feat/x-draft", readonly / "wt")
    finally:
        readonly.chmod(0o700)

    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    assert ws.path.is_dir()


def test_apply_back_refuses_a_symlinked_parent_pointing_inside_the_repo(
    repo: Path, tmp_path: Path
) -> None:
    # Pins the *component walk*, not the leaf. Here the leaf (src/pkg/mod.py) is
    # not itself a link and the redirect lands inside the repo, so both a
    # leaf-only dest.is_symlink() check and the _resolves_inside tail pass it --
    # only walking every component catches the parent. Without this test, a
    # future simplification to the leaf reopens the redirect bypass silently.
    (repo / "real").mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "pkg").symlink_to("../real", target_is_directory=True)

    ws = workspace.create(repo, "feat/x-draft", tmp_path / "wt")
    (ws.path / "src" / "pkg").mkdir(parents=True)
    (ws.path / "src" / "pkg" / "mod.py").write_text("x = 1\n")

    with pytest.raises(workspace.RedirectedDestination) as exc:
        workspace.apply_back(ws, ["src/pkg/"])

    assert exc.value.paths == ["src/pkg/mod.py"]
    assert not (repo / "real" / "mod.py").exists()


def test_the_branch_collision_remedy_orders_the_two_commands_correctly(
    repo: Path, tmp_path: Path
) -> None:
    """`git branch -D` refuses a branch a live worktree is still using.

    ``destroy`` keeps the branch by design, and the finish pass now also keeps the
    WORKTREE when apply-back was refused, so the two are reachable together. The remedy
    this refusal prints has to name the worktree removal FIRST, or an operator following
    it verbatim gets "cannot delete branch 'draft/x' used by worktree at ...".
    """
    workspace.create(repo, "draft/x", tmp_path / "wt")

    with pytest.raises(workspace.WorkspaceExists) as caught:
        workspace.create(repo, "draft/x", tmp_path / "wt2")

    message = str(caught.value)
    assert "git worktree remove --force" in message
    assert message.index("git worktree remove") < message.index("git branch -D")

    # Not taken on faith: the old remedy really does fail while the worktree is live.
    refused = subprocess.run(
        ["git", "branch", "-D", "draft/x"], cwd=repo, capture_output=True, text=True
    )
    assert refused.returncode != 0
    assert "worktree" in refused.stderr
