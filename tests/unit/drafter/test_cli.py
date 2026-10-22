"""The CLI's wiring, tested where it is defeatable rather than where it is visible.

Argument parsing is the cheap half. The expensive half is the set of joins that
fail by reporting success: a verification that never sees the brief, a status
resolved over a floor that cannot fail, a TODO in the module nobody scanned, a
golden module staged into the tree the agent is reading. Each of those has a test
below that fails if the wiring is removed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import (
    capture,
    cli,
    client,
    finish,
    inventory,
    loop,
    reader,
    scaffold,
    verify,
    workspace,
)

# --- the parser ---


def test_parser_exposes_every_subcommand() -> None:
    parser = cli.build_parser()
    for argv in (
        ["claim", "ok__osbi"],
        ["capture", "ok__osbi", "--refresh"],
        ["scaffold", "cold_case_ok_osbi"],
        ["draft", "cold_case_ok_osbi", "--rounds", "2"],
        ["verify", "cold_case_ok_osbi", "--live-check"],
        ["finish", "cold_case_ok_osbi"],
        ["run", "ok__osbi"],
    ):
        assert parser.parse_args(argv).command == argv[0]


def test_draft_defaults_to_three_rounds_and_opus() -> None:
    args = cli.build_parser().parse_args(["draft", "cold_case_ok_osbi"])
    assert args.rounds == 3
    assert "opus" in args.model


def test_the_agent_rounds_carry_a_budget_by_default() -> None:
    """There is no --max-turns in CLI 2.1.251, so this is the only non-clock bound."""
    for argv in (["draft", "a"], ["capture", "b"], ["run", "c"]):
        args = cli.build_parser().parse_args(argv)
        assert args.max_budget_usd == loop.DEFAULT_PARSER_BUDGET_USD
        assert args.max_budget_usd is not None


def test_the_capture_quality_refusals_have_an_operator_flag() -> None:
    """Task 7's three acceptances are unreachable without one, and default to none."""
    args = cli.build_parser().parse_args(
        ["capture", "x", "--accept-partial", "truncated", "--accept-partial", "empty"]
    )
    assert args.accept_partial == ["truncated", "empty"]
    assert cli.build_parser().parse_args(["capture", "x"]).accept_partial == []


def test_the_resume_guard_has_an_operator_flag() -> None:
    """capture(session_id=...) is the only caller of session.resume anywhere."""
    args = cli.build_parser().parse_args(["capture", "x", "--session-id", "s-1"])
    assert args.session_id == "s-1"
    assert cli.build_parser().parse_args(["capture", "x"]).session_id is None


def test_finish_has_no_force_flag_and_its_refusals_no_longer_prescribe_one() -> None:
    """All four `finish` pre-flight refusals used to end "`--force` breaks the lease".

    It does not exist on `finish`, and the detour through `claim --force` is unreachable
    by then: `_claim` refuses a dirty checkout before it reaches `lease.acquire`, and by
    the time anyone is at `finish` the scaffold's own output has made the checkout dirty.
    An operator following the message exactly could not proceed at all.
    """
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["finish", "cold_case_zz_x", "--force"])
    assert "delete data/drafts/<adapter>/lease.json" in finish.PREFLIGHT_UNTOUCHED
    assert "finish has no --force" in finish.PREFLIGHT_UNTOUCHED


def test_run_does_not_open_a_pull_request_unless_asked() -> None:
    assert cli.build_parser().parse_args(["run", "x"]).finish is False
    assert cli.build_parser().parse_args(["run", "x", "--finish"]).finish is True


# --- --dry-run ---


def test_dry_run_prints_the_prompt_without_invoking(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "_load_brief",
        lambda adapter, data_dir: {"adapter_name": adapter, "inventory_measured": True},
    )
    monkeypatch.setattr(loop, "build_round_prompt", lambda **kw: "PROMPT BODY")

    def explode(*a: Any, **k: Any) -> Any:
        raise AssertionError("client must not be invoked during --dry-run")

    monkeypatch.setattr(client, "SubprocessDrafterClient", explode)
    monkeypatch.setattr(workspace, "create", explode)

    assert cli.main(["draft", "cold_case_ok_osbi", "--dry-run"]) == 0
    assert "PROMPT BODY" in capsys.readouterr().out


def test_dry_run_on_the_run_chain_refuses_before_anything_is_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`run --dry-run` used to buy a reader round and then die for a file it never wrote.

    `_draft` honours the flag correctly and does it before the lease, the branch and the
    worktree; nothing on the chain did. `run cand-1 --dry-run` claimed the lease, crawled
    the whole source over the network, spent one real Opus reader round, scaffolded,
    printed the prompt, returned without writing workspace.json -- and then `_verify`
    refused for the missing workspace.json. Exit 1, money spent, no prompt-only run.
    """

    def explode(*a: Any, **k: Any) -> Any:
        raise AssertionError("nothing on the run chain may execute under --dry-run")

    for name in ("_claim", "_capture", "_scaffold", "_draft", "_verify", "_finish"):
        monkeypatch.setattr(cli, name, explode)

    assert cli.main(["--repo-root", str(tmp_path), "run", "cand-1", "--dry-run"]) == 1

    err = capsys.readouterr().err
    assert "FAIL [cli]" in err
    assert "capture cand-1" in err  # the two commands that DO give a prompt-only run
    assert "draft <adapter> --dry-run" in err


def test_an_over_ceiling_rounds_count_is_refused_before_the_run_chain_spends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ceiling was enforced in `_draft`, which runs AFTER `_capture` on this chain.

    So `run <cand> --rounds 500` claimed the lease, crawled the source and bought a full
    reader round before the bound that exists to stop an unattended bill refused it --
    the same defect class the same commit hoisted the fixtures and scaffold refusals out
    of, re-introduced beside them.
    """

    def explode(*a: Any, **k: Any) -> Any:
        raise AssertionError("nothing on the run chain may run for a rounds count we refuse")

    for name in ("_claim", "_capture", "_scaffold", "_draft", "_verify", "_finish"):
        monkeypatch.setattr(cli, name, explode)

    exit_code = cli.main(
        ["--repo-root", str(tmp_path), "run", "cand-1", "--rounds", str(loop.MAX_ROUNDS + 1)]
    )

    assert exit_code == 1
    assert "over the run ceiling" in capsys.readouterr().err


def test_an_over_ceiling_rounds_count_is_refused_before_the_lease_and_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_loop checks it too, but only after workspace.create -- which is a cleanup."""
    monkeypatch.setattr(
        cli,
        "_load_brief",
        lambda adapter, data_dir: {"adapter_name": adapter, "inventory_measured": True},
    )

    def explode(*a: Any, **k: Any) -> Any:
        raise AssertionError("nothing may be claimed or cut for a rounds count we refuse")

    monkeypatch.setattr(cli, "_require_the_lease", explode)
    monkeypatch.setattr(workspace, "create", explode)

    args = cli.build_parser().parse_args(
        ["draft", "cold_case_ok_osbi", "--rounds", str(loop.MAX_ROUNDS + 1)]
    )
    with pytest.raises(loop.LoopRefusal, match="over the run ceiling"):
        cli._draft(args, tmp_path, tmp_path / "drafts")


# --- the measured-brief guard ---


def _measured(**over: Any) -> dict[str, Any]:
    brief: dict[str, Any] = {
        "adapter_name": "cold_case_zz_x",
        "inventory_measured": True,
        "floors": {"case_name": 0.95},
    }
    brief.update(over)
    return brief


@pytest.mark.parametrize(
    "flag", [False, None, "true", "True", 1, "yes"], ids=["false", "none", "str", "Str", "1", "yes"]
)
def test_an_unmeasured_brief_is_refused_by_identity_not_truthiness(flag: object) -> None:
    """`"true"` off a JSON round trip is truthy and means nothing was measured.

    verify.build_report's own guard tests ``is True``, so a string fails open there
    exactly as None does. This is where it is caught with a message naming the pass.
    """
    with pytest.raises(verify.UnusableBrief):
        cli._require_a_measured_brief({"inventory_measured": flag}, "verify")


def test_a_measured_brief_passes_the_guard() -> None:
    cli._require_a_measured_brief(_measured(), "verify")


def test_dry_run_refuses_an_unmeasured_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prompt quotes the brief's floors; an unmeasured one describes nothing."""
    monkeypatch.setattr(cli, "_load_brief", lambda adapter, data_dir: {"adapter_name": adapter})
    assert cli.main(["draft", "cold_case_ok_osbi", "--dry-run"]) == 1


# --- stage attribution ---


def test_a_verify_stage_refusal_is_not_attributed_to_the_scaffold() -> None:
    """UnusableBrief -> UnmeasuredBrief -> ScaffoldRefusal: order is the whole content."""
    assert cli.stage_of(verify.UnusableBrief("x")) == "verify"
    assert cli.stage_of(scaffold.UnmeasuredBrief("x")) == "inventory"
    assert cli.stage_of(scaffold.ScaffoldRefusal("x")) == "scaffold"


def test_a_grading_environment_failure_is_attributed_to_the_environment() -> None:
    """Not to a pass. The refusal's whole value is that it says the draft is not at fault.

    Naming a pass would send the operator to re-run the one thing that cannot fix it,
    and this is raised from inside `draft` as well as from `verify`, so no pass name is
    true of both.
    """
    assert cli.stage_of(verify.MissingGradingEnvironment("x")) == "environment"


def test_the_cli_names_stages_for_the_refusals_finish_does_not_know() -> None:
    assert cli.stage_of(capture.Refused("x")) == "capture"
    assert cli.stage_of(reader.InvalidReaderOutput("x")) == "reader"
    assert cli.stage_of(inventory.NothingToMeasure("x")) == "inventory"
    assert cli.stage_of(cli.CliRefusal("x")) == "cli"
    assert cli.stage_of(RuntimeError("x")) == "unknown"


def test_main_reports_a_refusal_with_its_stage_and_never_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(adapter: str, data_dir: Path) -> dict[str, Any]:
        raise verify.UnusableBrief("the floors assert nothing")

    monkeypatch.setattr(cli, "_load_brief", refuse)
    assert cli.main(["draft", "x", "--dry-run"]) == 1
    assert "FAIL [verify] UnusableBrief" in capsys.readouterr().err


def test_an_unrecognised_exception_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(adapter: str, data_dir: Path) -> dict[str, Any]:
        raise ZeroDivisionError("a real defect")

    monkeypatch.setattr(cli, "_load_brief", boom)
    with pytest.raises(ZeroDivisionError):
        cli.main(["draft", "x", "--dry-run"])


# --- what the loop is handed ---


def test_the_golden_module_is_never_staged_into_the_worktree() -> None:
    """Staging it hands the parser pass the answers it is graded against."""
    paths = cli._scaffold_paths({"state": "ZZ"}, "cold_case_zz_x")
    assert "tests/unit/etl/adapters/test_cold_case_zz_x_invariants.py" in paths
    assert "tests/unit/etl/adapters/test_cold_case_zz_x_expectations.py" not in paths


def test_the_staged_set_is_everything_the_scaffold_wrote_but_the_answers() -> None:
    paths = set(cli._scaffold_paths({"state": "ZZ"}, "cold_case_zz_x"))
    assert paths == {
        "src/casesignal/etl/adapters/cold_case_zz_x",
        "tests/unit/etl/adapters/test_cold_case_zz_x_invariants.py",
        "tests/fixtures/cold_case_zz_x",
        "docs/drafts/cold_case_zz_x.md",
        "src/casesignal/etl/runners/run_pipeline.py",
        "src/casesignal/etl/sources/cold_case_zz.yaml",
    }


def test_the_shared_file_is_in_the_staged_set_and_is_warned_about() -> None:
    """run_pipeline.py is the one file a draft shares with the rest of the repo."""
    assert cli._SHARED_FILE in cli._scaffold_paths({"state": "ZZ"}, "a")
    assert cli._SHARED_FILE in finish.draft_owned_paths({"adapter_name": "a"})


def test_the_generated_fixtures_are_staged_by_finish() -> None:
    """Both generated modules read tests/fixtures/<adapter>; an unstaged one is a red PR."""
    assert "tests/fixtures/cold_case_zz_x" in finish.draft_owned_paths(
        {"adapter_name": "cold_case_zz_x"}
    )


def test_the_injected_golden_module_is_rewritten_to_an_absolute_fixtures_root(
    tmp_path: Path,
) -> None:
    """Injected at the worktree root, parents[3] lands three directories above it."""
    repo_root = tmp_path / "repo"
    ws = workspace.Workspace(branch="drafts/a", path=tmp_path / "wt" / "a", repo_root=repo_root)
    source = repo_root / "tests/unit/etl/adapters/test_a_expectations.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from pathlib import Path\n"
        'FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "a"\n'
        'EXPECTATIONS = {"listing_1.html#0": {"case_name": "ALICE"}}\n',
        encoding="utf-8",
    )
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()

    prepared = cli._prepare_expectation_module(ws, draft_dir, "a")

    assert prepared.parent == draft_dir  # outside the worktree: run_loop refuses otherwise
    text = prepared.read_text(encoding="utf-8")
    assert "parents[3]" not in text
    assert str((ws.path / "tests" / "fixtures" / "a").resolve()) in text
    assert "ALICE" in text  # the golden values themselves are untouched


def test_a_module_without_the_generated_fixtures_line_is_refused(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    ws = workspace.Workspace(branch="b", path=tmp_path / "wt", repo_root=repo_root)
    source = repo_root / "tests/unit/etl/adapters/test_a_expectations.py"
    source.parent.mkdir(parents=True)
    source.write_text("FIXTURES_ROOT = 'somewhere else'\n", encoding="utf-8")
    with pytest.raises(cli.CliRefusal, match="FIXTURES_ROOT"):
        cli._prepare_expectation_module(ws, tmp_path, "a")


# --- verification ---


def _outcome(passed: bool = True) -> verify.TestOutcome:
    return verify.TestOutcome(passed=passed, failures=[], raw="", ran=True, returncode=0)


def test_verification_routes_through_build_report_with_the_whole_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A vacuous floor must not resolve to PASS. resolve_status cannot see it."""
    data_dir = tmp_path / "drafts"
    draft_dir = data_dir / "cold_case_zz_x"
    draft_dir.mkdir(parents=True)
    (draft_dir / "brief.json").write_text(
        json.dumps(_measured(floors={"case_name": 0.0}, vacuous_floors=["case_name"])),
        encoding="utf-8",
    )
    (draft_dir / "workspace.json").write_text(
        json.dumps({"branch": "b", "path": str(tmp_path / "wt"), "repo_root": str(tmp_path)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli, "_run_the_generated_modules", lambda ws, name: (_outcome(), _outcome())
    )
    monkeypatch.setattr(loop, "parser_module_paths", lambda root, name: [])

    args = cli.build_parser().parse_args(["--data-dir", str(data_dir), "verify", "cold_case_zz_x"])
    report = cli._verify(args, tmp_path, data_dir, "cold_case_zz_x")

    assert report.status is verify.VerifyStatus.FAIL
    assert "case_name" in " ".join(report.advisories)
    assert capsys.readouterr().out


def test_todos_are_scanned_in_both_parser_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """find_todos reads ONE path; a marked TODO in scrape.py otherwise resolves PASS."""
    data_dir = tmp_path / "drafts"
    draft_dir = data_dir / "cold_case_zz_x"
    draft_dir.mkdir(parents=True)
    (draft_dir / "brief.json").write_text(json.dumps(_measured()), encoding="utf-8")
    ws_path = tmp_path / "wt"
    (draft_dir / "workspace.json").write_text(
        json.dumps({"branch": "b", "path": str(ws_path), "repo_root": str(tmp_path)}),
        encoding="utf-8",
    )
    package = ws_path / loop.ADAPTER_PACKAGE_ROOT / "cold_case_zz_x"
    package.mkdir(parents=True)
    (package / "scrape.py").write_text("# TODO(county): not parsed\n", encoding="utf-8")
    (package / "transform.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        cli, "_run_the_generated_modules", lambda ws, name: (_outcome(), _outcome())
    )

    args = cli.build_parser().parse_args(["verify", "cold_case_zz_x"])
    report = cli._verify(args, tmp_path, data_dir, "cold_case_zz_x")

    assert [todo.field for todo in report.todos] == ["county"]
    assert report.status is verify.VerifyStatus.PASS_WITH_TODOS


def test_a_missing_transform_module_fails_the_verify_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "drafts"
    draft_dir = data_dir / "cold_case_zz_x"
    draft_dir.mkdir(parents=True)
    (draft_dir / "brief.json").write_text(json.dumps(_measured()), encoding="utf-8")
    (draft_dir / "workspace.json").write_text(
        json.dumps({"branch": "b", "path": str(tmp_path / "wt"), "repo_root": str(tmp_path)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli, "_run_the_generated_modules", lambda ws, name: (_outcome(), _outcome())
    )

    assert cli.main(["--data-dir", str(data_dir), "verify", "cold_case_zz_x"]) == 1
    assert "FAIL [verify] TransformNotDrafted" in capsys.readouterr().err


# --- the branch this draft lands on ---


class _FakeRunner:
    """Answers the git queries the CLI and finish make, and records the rest."""

    def __init__(self, branch: str = "feat/x", branches: tuple[str, ...] = ()) -> None:
        self.branch = branch
        self.branches = branches
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
        self.calls.append(list(cmd))
        args = cmd[1:]
        out, code = "", 0
        if args[:3] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            out = f"{self.branch}\n"
        elif args[:2] == ["symbolic-ref", "refs/remotes/origin/HEAD"]:
            code = 1
        elif args[:2] == ["config", "--get-all"]:
            # Task 14 added this query; a double scripted to a fixed command set
            # would see a command it does not know.
            code = 1
        elif args[:2] == ["branch", "--list"]:
            out = f"  {args[2]}\n" if args[2] in self.branches else ""
        elif args[0] == "checkout":
            self.branch = args[-1]
        elif args[:2] == ["diff", "--cached"]:
            out = ""
        elif args[0] == "status":
            out = ""
        elif args[:2] == ["worktree", "list"]:
            out = ""

        class _Proc:
            returncode = code
            stdout = out
            stderr = ""

        return _Proc()


def test_a_protected_branch_is_refused_before_the_worktree_is_created(tmp_path: Path) -> None:
    runner = _FakeRunner(branch="main")
    with pytest.raises(cli.CliRefusal, match="protected"):
        cli._destination_branch(runner, tmp_path, None, "cold_case_zz_x")


def test_the_protected_list_is_the_one_finish_enforces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One list and one escape hatch, or the cheap layer disagrees with the real one."""
    monkeypatch.setenv(finish.PROTECTED_BRANCH_ENV, "release/live")
    runner = _FakeRunner(branch="release/live")
    with pytest.raises(cli.CliRefusal, match="release/live"):
        cli._destination_branch(runner, tmp_path, None, "a")


def test_an_explicit_branch_is_created_and_checked_out(tmp_path: Path) -> None:
    runner = _FakeRunner(branch="main")
    assert cli._destination_branch(runner, tmp_path, "draft/a", "a") == "draft/a"
    assert ["git", "checkout", "-b", "draft/a"] in runner.calls


def test_an_existing_branch_is_checked_out_without_b(tmp_path: Path) -> None:
    runner = _FakeRunner(branch="main", branches=("draft/a",))
    assert cli._destination_branch(runner, tmp_path, "draft/a", "a") == "draft/a"
    assert ["git", "checkout", "draft/a"] in runner.calls


def test_an_explicitly_protected_branch_is_refused_too(tmp_path: Path) -> None:
    runner = _FakeRunner(branch="feat/x")
    with pytest.raises(cli.CliRefusal, match="protected"):
        cli._destination_branch(runner, tmp_path, "main", "a")


def test_a_detached_head_is_refused(tmp_path: Path) -> None:
    runner = _FakeRunner(branch="HEAD")
    with pytest.raises(cli.CliRefusal):
        cli._destination_branch(runner, tmp_path, None, "a")


# --- the operator's own work ---


def test_a_staged_index_is_refused(tmp_path: Path) -> None:
    class _Staged(_FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
            proc = super().__call__(cmd, **kwargs)
            if cmd[1:3] == ["diff", "--cached"]:
                proc.stdout = "src/thing.py\n"
            return proc

    with pytest.raises(cli.CliRefusal, match="staged"):
        cli._refuse_a_dirty_index(_Staged(), tmp_path)


def test_a_dirty_checkout_is_refused_at_claim(tmp_path: Path) -> None:
    class _Dirty(_FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
            proc = super().__call__(cmd, **kwargs)
            if cmd[1] == "status":
                proc.stdout = " M src/thing.py\0?? other.py\0"
            return proc

    with pytest.raises(cli.CliRefusal, match="uncommitted"):
        cli._refuse_a_dirty_checkout(_Dirty(), tmp_path)


def test_kept_worktrees_are_surfaced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Only a refused apply-back keeps one, and nothing prunes them."""

    class _Kept(_FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
            proc = super().__call__(cmd, **kwargs)
            if cmd[1:3] == ["worktree", "list"]:
                proc.stdout = (
                    "worktree /repo\nbranch refs/heads/main\n\n"
                    "worktree /repo/.worktrees/cold_case_zz_x\n"
                    "branch refs/heads/drafts/cold_case_zz_x\n\n"
                )
            return proc

    cli._report_kept_worktrees(_Kept(), tmp_path)
    printed = capsys.readouterr().out
    assert ".worktrees/cold_case_zz_x" in printed
    assert "git branch -D drafts/cold_case_zz_x" in printed
    assert "/repo\n" not in printed.replace(".worktrees", "")


# --- the outcome an operator reads without opening a file ---


def test_the_exit_message_names_the_branch_the_commit_landed_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / finish.OUTCOME_FILE).write_text(
        json.dumps(
            {"committed_to": "draft/a", "pushed": True, "worktree_kept": False, "warnings": []}
        ),
        encoding="utf-8",
    )
    cli._report_the_outcome(tmp_path, "https://example.invalid/pull/1")
    out = capsys.readouterr().out
    assert "committed to: draft/a" in out
    assert "pushed=True" in out


def test_an_adopted_pull_request_says_the_body_was_not_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / finish.OUTCOME_FILE).write_text(
        json.dumps(
            {
                "committed_to": "draft/a",
                "pushed": True,
                "warnings": [
                    "`gh pr create` failed; adopted the pull request already open at "
                    "https://example.invalid/pull/2. ITS BODY WAS NOT UPDATED"
                ],
            }
        ),
        encoding="utf-8",
    )
    cli._report_the_outcome(tmp_path, "https://example.invalid/pull/2")
    out = capsys.readouterr().out
    assert "was NOT published" in out
    assert finish.PR_BODY_FILE in out


# --- the worktree's own casesignal has to be the one that is imported ---


def test_the_worktree_src_goes_ahead_of_the_editable_install(tmp_path: Path) -> None:
    ws = workspace.Workspace(branch="b", path=tmp_path / "wt", repo_root=tmp_path)
    import os

    before = os.environ.get("PYTHONPATH")
    with cli._worktree_on_the_path(ws):
        assert os.environ["PYTHONPATH"].split(os.pathsep)[0] == str((ws.path / "src").resolve())
    assert os.environ.get("PYTHONPATH") == before


# --- what capture and the loop are actually handed ---


def test_capture_runs_the_reader_and_then_the_inventory_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NOTHING ELSE in the repository calls write_measured_brief.

    Without this call brief.json keeps ``inventory_measured: false``, every floor
    the generator would render is a number nobody measured, and the failure arrives
    through a handoff gap rather than through a bug in any module.
    """
    from casesignal.drafter.session import CaptureSession
    from casesignal.drafter.shapes.base import CaptureResult
    from casesignal.scout.models import Candidate, Channel, Level

    candidate = Candidate(
        id="x", level=Level.STATE, state="ZZ", index_url="https://x.invalid/", channel=Channel.WEB
    )
    outcome = capture.CaptureOutcome(
        result=CaptureResult(listing_paths=["listing_1.html"], records_captured=1),
        session=CaptureSession(
            session_id="s", shape="html", started_at="t", fixtures_root="fixtures"
        ),
        shape="html",
    )

    class _Measurement:
        floors = {"case_name": 0.95}
        omitted = ("race",)
        unreachable_floors = ()
        vacuous_floors = ()
        suspected_page_mismatch = ()

    recorded: dict[str, Any] = {}

    def fake_write(draft_dir: Path, cand: Any, out: Any, locators: Any, **kw: Any) -> Any:
        recorded.update(
            {"draft_dir": draft_dir, "candidate": cand, "outcome": out, "locators": locators, **kw}
        )
        return (draft_dir / "brief.json", _Measurement())

    asked: dict[str, Any] = {}

    def fake_reader(cand: Any, agent: Any, **kw: Any) -> Any:
        asked.update(kw)
        return ({"victim_name": object()}, [])

    monkeypatch.setattr(cli, "_load_candidate", lambda registry, cid: candidate)
    monkeypatch.setattr(cli, "_require_the_lease", lambda draft_dir, name: None)
    monkeypatch.setattr(cli, "_http_client_factory", lambda: lambda **kw: object())
    monkeypatch.setattr(cli, "_drafter_client", lambda: object())
    monkeypatch.setattr(capture, "capture", lambda cand, **kw: outcome)
    monkeypatch.setattr(reader, "run_reader", fake_reader)
    monkeypatch.setattr(inventory, "write_measured_brief", fake_write)

    data_dir = tmp_path / "drafts"
    args = cli.build_parser().parse_args(
        ["capture", "x", "--adapter-name", "cold_case_zz_x", "--accept-partial", "truncated"]
    )
    assert cli._capture(args, tmp_path, data_dir) == "cold_case_zz_x"

    assert recorded["draft_dir"] == data_dir / "cold_case_zz_x"
    assert recorded["outcome"] is outcome
    assert set(recorded["locators"]) == {"victim_name"}
    assert recorded["adapter_name"] == "cold_case_zz_x"
    assert list(recorded["accepted"]) == ["truncated"]
    # The reader reads the capture's own fixtures, named through the session's root.
    assert asked["fixture_paths"] == ["fixtures/listing_1.html"]
    assert asked["max_budget_usd"] is not None


def test_the_loop_is_handed_expectations_real_test_paths_and_a_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three defaults that are each a silent failure when left to themselves."""
    data_dir = tmp_path / "drafts"
    draft_dir = data_dir / "cold_case_zz_x"
    draft_dir.mkdir(parents=True)
    (draft_dir / "brief.json").write_text(json.dumps(_measured()), encoding="utf-8")
    (draft_dir / "expectations.json").write_text(
        json.dumps([{"record_key": "listing_1.html#0", "values": {"victim_name": "ALICE"}}]),
        encoding="utf-8",
    )
    _write_scaffold(tmp_path, "cold_case_zz_x")
    ws = workspace.Workspace(branch="drafts/x", path=tmp_path / "wt", repo_root=tmp_path)
    seen: dict[str, Any] = {}

    def fake_run_loop(**kwargs: Any) -> loop.LoopReport:
        seen.update(kwargs)
        return loop.LoopReport(rounds=[], passed=True, stopped_because="green")

    monkeypatch.setattr(cli, "_runner", lambda: _FakeRunner(branch="draft/x"))
    monkeypatch.setattr(cli, "_require_the_lease", lambda draft_dir, name: None)
    monkeypatch.setattr(workspace, "create", lambda root, branch, path: ws)
    monkeypatch.setattr(cli, "_stage_the_scaffold", lambda runner, w, brief, name: [])
    monkeypatch.setattr(
        cli, "_prepare_expectation_module", lambda w, d, name: d / "expectation_module.py"
    )
    monkeypatch.setattr(cli, "_drafter_client", lambda: object())
    monkeypatch.setattr(loop, "run_loop", fake_run_loop)

    args = cli.build_parser().parse_args(["--data-dir", str(data_dir), "draft", "cold_case_zz_x"])
    cli._draft(args, tmp_path, data_dir)

    # Omitted, the redaction's value scan is off and a failure line quoting a golden
    # value goes straight back into the next prompt.
    assert [record.record_key for record in seen["expectations"]] == ["listing_1.html#0"]
    # Empty, and pytest falls back to `testpaths` and runs the whole repository suite.
    assert seen["test_paths"] == [Path("tests/unit/etl/adapters/test_cold_case_zz_x_invariants.py")]
    # Omitted, and nothing but the wall clock bounds the round.
    assert seen["max_budget_usd"] == loop.DEFAULT_PARSER_BUDGET_USD
    # Both must be outside the worktree, or the agent can read the answers.
    assert not str(seen["artifacts_dir"]).startswith(str(ws.path))
    assert not str(seen["expectation_module"]).startswith(str(ws.path))
    assert json.loads((draft_dir / "loop.json").read_text())["stopped_because"] == "green"


def test_an_existing_pythonpath_is_kept_behind_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appending instead of prepending puts the operator's checkout in front again."""
    import os

    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    ws = workspace.Workspace(branch="b", path=tmp_path / "wt", repo_root=tmp_path)
    with cli._worktree_on_the_path(ws):
        entries = os.environ["PYTHONPATH"].split(os.pathsep)
        assert entries[0] == str((ws.path / "src").resolve())
        assert "/somewhere/else" in entries
    assert os.environ["PYTHONPATH"] == "/somewhere/else"


# --- a draft with no scaffold under it ---


def _write_scaffold(repo_root: Path, adapter: str) -> None:
    """The three paths a drafting round cannot run without."""
    package = repo_root / loop.ADAPTER_PACKAGE_ROOT / adapter
    package.mkdir(parents=True, exist_ok=True)
    (package / "adapter.py").write_text("", encoding="utf-8")
    tests_dir = repo_root / "tests" / "unit" / "etl" / "adapters"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / f"test_{adapter}_invariants.py").write_text("", encoding="utf-8")
    (tests_dir / f"test_{adapter}_expectations.py").write_text("", encoding="utf-8")


def _draft_args(data_dir: Path, adapter: str) -> Any:
    return cli.build_parser().parse_args(["--data-dir", str(data_dir), "draft", adapter])


def _drafting_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, _FakeRunner]:
    """A brief, a lease and a runner: everything `draft` needs except the scaffold."""
    data_dir = tmp_path / "drafts"
    draft_dir = data_dir / "cold_case_zz_x"
    draft_dir.mkdir(parents=True)
    (draft_dir / "brief.json").write_text(json.dumps(_measured()), encoding="utf-8")
    (draft_dir / "expectations.json").write_text("[]", encoding="utf-8")
    runner = _FakeRunner(branch="feat/x")
    monkeypatch.setattr(cli, "_runner", lambda: runner)
    monkeypatch.setattr(cli, "_require_the_lease", lambda draft_dir, name: None)
    return data_dir, runner


def test_a_draft_with_no_scaffold_is_refused_before_the_worktree_is_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It used to strand a worktree and a branch, then raise a bare FileNotFoundError.

    Nothing was spent -- this is before round 0 -- but the retry was blocked until the
    operator removed the worktree and deleted the branch by hand.
    """
    data_dir, runner = _drafting_state(tmp_path, monkeypatch)

    def explode(*a: Any, **k: Any) -> Any:
        raise AssertionError("no worktree may be cut for a draft with no scaffold")

    monkeypatch.setattr(workspace, "create", explode)

    with pytest.raises(cli.CliRefusal, match="scaffold"):
        cli._draft(_draft_args(data_dir, "cold_case_zz_x"), tmp_path, data_dir)

    # And before the branch, which _destination_branch would have CHECKED OUT.
    assert not [call for call in runner.calls if call[1:2] == ["checkout"]]


def test_the_missing_scaffold_refusal_names_every_path_and_the_pass_to_re_run(
    tmp_path: Path,
) -> None:
    with pytest.raises(cli.CliRefusal) as caught:
        cli._require_the_scaffold(tmp_path, "cold_case_zz_x")
    message = str(caught.value)
    assert "src/casesignal/etl/adapters/cold_case_zz_x" in message
    assert "test_cold_case_zz_x_invariants.py" in message
    assert "test_cold_case_zz_x_expectations.py" in message
    assert "scaffold cold_case_zz_x" in message


def test_a_scaffold_missing_only_the_golden_module_is_refused(tmp_path: Path) -> None:
    """That absence is the one that used to escape as an unattributed FileNotFoundError."""
    _write_scaffold(tmp_path, "cold_case_zz_x")
    golden = tmp_path / "tests/unit/etl/adapters/test_cold_case_zz_x_expectations.py"
    golden.unlink()
    with pytest.raises(cli.CliRefusal, match="expectations.py"):
        cli._require_the_scaffold(tmp_path, "cold_case_zz_x")


def test_a_complete_scaffold_passes_the_pre_flight(tmp_path: Path) -> None:
    _write_scaffold(tmp_path, "cold_case_zz_x")
    cli._require_the_scaffold(tmp_path, "cold_case_zz_x")


def test_staging_refuses_rather_than_staging_nothing_into_the_worktree(
    tmp_path: Path,
) -> None:
    """`staged 0 scaffold path(s)` was a signal printed to nobody. It is unreachable now."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    ws = workspace.Workspace(branch="drafts/x", path=tmp_path / "wt", repo_root=repo_root)
    runner = _FakeRunner()
    with pytest.raises(cli.CliRefusal, match="scaffold"):
        cli._stage_the_scaffold(runner, ws, _measured(), "cold_case_zz_x")
    assert not [call for call in runner.calls if call[1:2] == ["commit"]]


# --- the advisory live check ---


def _manifest(draft_dir: Path, url: str, digest: str) -> None:
    (draft_dir / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": "s-1",
                "shape": "html",
                "started_at": "2026-09-01T00:00:00Z",
                "fixtures_root": "fixtures",
                "fixtures": [
                    {
                        "path": "listing_1.html",
                        "url": url,
                        "status": 200,
                        "sha256": digest,
                        "fetched_at": "2026-09-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class _LiveClient:
    """A polite-client stand-in that answers, or raises, exactly once."""

    def __init__(self, body: bytes = b"", error: Exception | None = None, **kwargs: Any) -> None:
        self.body = body
        self.error = error
        self.kwargs = kwargs
        self.requested: list[str] = []
        self.closed = False

    def get(self, url: str) -> Any:
        self.requested.append(url)
        if self.error is not None:
            raise self.error

        class _Response:
            content = self.body
            status_code = 200

        return _Response()

    def close(self) -> None:
        self.closed = True


def _live_client(monkeypatch: pytest.MonkeyPatch, client_obj: _LiveClient) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _LiveClient:
        seen.update(kwargs)
        return client_obj

    monkeypatch.setattr(cli, "_http_client_factory", lambda: factory)
    return seen


def test_a_live_check_reports_a_page_that_still_matches_the_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    body = b"<html>the page as captured</html>"
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, url, hashlib.sha256(body).hexdigest())
    held = _LiveClient(body=body)
    seen = _live_client(monkeypatch, held)

    lines = cli._source_drift_check(tmp_path, _measured(index_url=url, transport="curl_cffi"), 5)

    assert "byte-identical" in " ".join(lines)
    assert "1 of 5 budgeted request(s) used" in lines[-1]
    assert held.requested == [url]
    assert held.closed is True
    # The whole point of the budget is that it sits BELOW the client's own guards.
    assert seen["allowed_hosts"] == frozenset({"example.invalid"})
    assert seen["bypass_robots_hosts"] == frozenset()
    assert seen["tls_impersonate"] is True


def test_a_live_check_says_when_the_source_has_moved_under_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, url, "0" * 64)
    _live_client(monkeypatch, _LiveClient(body=b"a page nobody transcribed"))

    lines = cli._source_drift_check(tmp_path, _measured(index_url=url), 5)

    assert "NO LONGER matches" in " ".join(lines)
    assert "re-capture" in " ".join(lines)


def test_a_live_check_with_no_digest_for_the_index_url_compares_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, "https://example.invalid/other", "0" * 64)
    _live_client(monkeypatch, _LiveClient(body=b"x"))

    lines = cli._source_drift_check(tmp_path, _measured(index_url=url), 5)

    assert "no digest for the index URL" in " ".join(lines)


def test_a_live_check_with_no_usable_index_url_asks_for_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = _LiveClient()
    _live_client(monkeypatch, held)
    lines = cli._source_drift_check(tmp_path, _measured(index_url=""), 5)
    assert "nothing to check" in " ".join(lines)
    assert held.requested == []


def test_a_live_check_without_a_manifest_has_nothing_to_compare_against(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = _LiveClient()
    _live_client(monkeypatch, held)
    lines = cli._source_drift_check(tmp_path, _measured(index_url="https://example.invalid/x"), 5)
    assert "no capture manifest" in " ".join(lines)
    assert held.requested == []


def test_the_live_check_budget_refuses_the_request_it_would_go_over_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, url, "0" * 64)
    held = _LiveClient(body=b"x")
    _live_client(monkeypatch, held)

    lines = cli._source_drift_check(tmp_path, _measured(index_url=url), 0)

    assert "request budget exhausted" in " ".join(lines)
    assert held.requested == []  # charged and refused before the delegate is called
    assert held.closed is True


def test_a_live_check_that_cannot_reach_the_source_is_an_advisory_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline, a DNS hiccup, a TLS failure, a robots refusal: none is news about the draft."""
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, url, "0" * 64)
    held = _LiveClient(error=OSError("Name or service not known"))
    _live_client(monkeypatch, held)

    lines = cli._source_drift_check(tmp_path, _measured(index_url=url), 5)

    assert "the live fetch FAILED" in " ".join(lines)
    assert "Name or service not known" in " ".join(lines)
    assert "the status above stands" in " ".join(lines)
    assert held.closed is True


def test_a_client_that_cannot_even_be_built_is_an_advisory_line_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The polite client resolves the host as it is constructed; that can refuse."""
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, url, "0" * 64)

    def factory(**kwargs: Any) -> Any:
        raise RuntimeError("no route to host")

    monkeypatch.setattr(cli, "_http_client_factory", lambda: factory)

    lines = cli._source_drift_check(tmp_path, _measured(index_url=url), 5)

    assert "the live fetch FAILED" in " ".join(lines)
    assert "no route to host" in " ".join(lines)
    assert not [line for line in lines if "budgeted request(s) used" in line]


def test_an_unreachable_live_check_does_not_fail_a_verify_that_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run-book calls it advisory. It used to abort verify with a traceback."""
    data_dir = tmp_path / "drafts"
    draft_dir = data_dir / "cold_case_zz_x"
    draft_dir.mkdir(parents=True)
    url = "https://example.invalid/cold-cases"
    (draft_dir / "brief.json").write_text(
        json.dumps(_measured(index_url=url)), encoding="utf-8"
    )
    (draft_dir / "workspace.json").write_text(
        json.dumps({"branch": "b", "path": str(tmp_path / "wt"), "repo_root": str(tmp_path)}),
        encoding="utf-8",
    )
    _manifest(draft_dir, url, "0" * 64)
    _live_client(monkeypatch, _LiveClient(error=OSError("Network is unreachable")))
    monkeypatch.setattr(
        cli, "_run_the_generated_modules", lambda ws, name: (_outcome(), _outcome())
    )
    monkeypatch.setattr(loop, "parser_module_paths", lambda root, name: [])

    code = cli.main(["--data-dir", str(data_dir), "verify", "cold_case_zz_x", "--live-check"])

    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out
    assert "live" in out


# --- the fixtures the pull request ships ---


def test_the_fixtures_the_brief_names_are_copied_where_the_tests_look(
    tmp_path: Path,
) -> None:
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    (draft_dir / "fixtures").mkdir(parents=True)
    (draft_dir / "fixtures" / "listing_1.html").write_text("one", encoding="utf-8")
    (draft_dir / "fixtures" / "detail_1.html").write_text("two", encoding="utf-8")
    repo_root = tmp_path / "repo"

    copied, pruned = _copy(draft_dir, repo_root, ["listing_1.html", "detail_1.html"])

    assert (copied, pruned) == (2, 0)
    target = repo_root / "tests" / "fixtures" / "cold_case_zz_x"
    assert sorted(entry.name for entry in target.iterdir()) == [
        cli.FIXTURES_MARKER,
        "detail_1.html",
        "listing_1.html",
    ]
    # The marker is what makes the NEXT run's prune allowed at all.
    assert "PRUNED" in (target / cli.FIXTURES_MARKER).read_text(encoding="utf-8")


def _copy(draft_dir: Path, repo_root: Path, wanted: list[str]) -> tuple[int, int]:
    return cli._copy_fixtures(draft_dir, repo_root, "cold_case_zz_x", wanted)


def test_a_re_capture_does_not_leave_superseded_fixtures_in_the_pull_request(
    tmp_path: Path,
) -> None:
    """finish stages the whole directory; a stale page reads as current evidence."""
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    (draft_dir / "fixtures").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    pages = ("listing_1.html", "listing_2.html", "listing_3.html")
    for name in pages:
        (draft_dir / "fixtures" / name).write_text(name, encoding="utf-8")
    assert _copy(draft_dir, repo_root, list(pages)) == (3, 0)

    # The re-capture walked one page. session.start does not delete the old fixture
    # files under the draft either, so copying the directory would carry them over.
    copied, pruned = _copy(draft_dir, repo_root, ["listing_1.html"])

    target = repo_root / "tests" / "fixtures" / "cold_case_zz_x"
    assert (copied, pruned) == (1, 2)
    assert sorted(entry.name for entry in target.iterdir()) == [
        cli.FIXTURES_MARKER,
        "listing_1.html",
    ]
    # The stale pages are still under data/drafts, which is why copying the whole
    # directory is not the same fix as copying what the brief names.
    assert (draft_dir / "fixtures" / "listing_3.html").is_file()


def test_a_brief_naming_a_fixture_that_is_not_on_disk_is_refused(tmp_path: Path) -> None:
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    (draft_dir / "fixtures").mkdir(parents=True)
    with pytest.raises(cli.CliRefusal, match="listing_1.html"):
        _copy(draft_dir, tmp_path / "repo", ["listing_1.html"])


# --- the chained finish ---


def _chained(
    monkeypatch: pytest.MonkeyPatch, status: verify.VerifyStatus, passed: bool
) -> list[str]:
    finished: list[str] = []
    report = loop.LoopReport(rounds=[], passed=passed, stopped_because="green")
    monkeypatch.setattr(cli, "_claim", lambda *a, **k: ("cand", "cold_case_zz_x"))
    monkeypatch.setattr(cli, "_capture", lambda *a, **k: "cold_case_zz_x")
    monkeypatch.setattr(cli, "_scaffold", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_draft", lambda *a, **k: report)
    monkeypatch.setattr(
        cli,
        "_verify",
        lambda *a, **k: verify.VerifyReport(
            status=status,
            invariants=_outcome(passed),
            expectations=_outcome(passed),
            todos=[],
            coverage={},
        ),
    )

    def fake_finish(*a: Any, **k: Any) -> str:
        finished.append("pushed")
        return "url"

    monkeypatch.setattr(cli, "_finish", fake_finish)
    return finished


def test_run_finish_does_not_push_a_red_draft_it_was_asked_to_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--finish is passed before the verdict exists; the operator has not read it yet."""
    finished = _chained(monkeypatch, verify.VerifyStatus.FAIL, passed=False)

    assert cli.main(["--repo-root", str(tmp_path), "run", "x", "--finish"]) == 1

    assert finished == []
    out = capsys.readouterr().out
    assert "NOT finishing" in out
    assert "finish cold_case_zz_x" in out  # the explicit command, if they mean it


def test_an_explicit_finish_over_a_red_draft_is_still_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A red draft is a reviewable artifact and its title says FAIL. The gate is on
    the chained path only: `finish` typed by hand is read as deliberate."""
    finished: list[str] = []

    def fake_finish(*a: Any, **k: Any) -> str:
        finished.append("pushed")
        return "url"

    monkeypatch.setattr(cli, "_finish", fake_finish)
    assert cli.main(["--repo-root", str(tmp_path), "finish", "cold_case_zz_x"]) == 0
    assert finished == ["pushed"]


def test_a_draft_with_todos_still_chains_into_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PASS_WITH_TODOS is what a partial adapter for a human to complete looks like."""
    finished = _chained(monkeypatch, verify.VerifyStatus.PASS_WITH_TODOS, passed=True)
    assert cli.main(["--repo-root", str(tmp_path), "run", "x", "--finish"]) == 0
    assert finished == ["pushed"]


# --- the constant refusals, asked before a dollar is spent ---


def _claim_candidate() -> Any:
    from casesignal.scout.models import Candidate, Channel, Level

    return Candidate(
        id="cand-1",
        level=Level.STATE,
        state="ZZ",
        index_url="https://x.invalid/",
        channel=Channel.WEB,
    )


def _no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any git call proves the refusal fired later than it should have.

    Both refusals below are decidable from the adapter name alone, so they must land
    ahead of every other pre-flight in `_claim` -- which is to say ahead of the first
    `git` invocation, and a very long way ahead of the crawl and the reader round that
    `run` chains after it.
    """

    def explode(*a: Any, **k: Any) -> Any:
        raise AssertionError("git ran before a refusal that needs nothing from git")

    monkeypatch.setattr(cli, "_load_candidate", lambda registry, cid: _claim_candidate())
    monkeypatch.setattr(cli, "_runner", lambda: explode)


def test_a_colliding_fixtures_directory_is_refused_at_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run <cand> --adapter-name fdle` used to spend a full reader round, then refuse."""
    _no_git(monkeypatch)
    repo = tmp_path / "repo"
    curated = repo / "tests" / "fixtures" / "fdle"
    curated.mkdir(parents=True)
    (curated / "fdle_case.html").write_text("another suite's evidence", encoding="utf-8")
    args = cli.build_parser().parse_args(["claim", "cand-1", "--adapter-name", "fdle"])

    with pytest.raises(cli.CliRefusal, match="did not write it"):
        cli._claim(args, repo, tmp_path / "drafts")

    assert not (tmp_path / "drafts" / "fdle" / "lease.json").exists()


def test_a_hand_written_adapter_is_refused_at_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run <candidate whose name derives to a shipped adapter>`, the re-draft case."""
    _no_git(monkeypatch)
    repo = tmp_path / "repo"
    package = repo / "src" / "casesignal" / "etl" / "adapters" / "cold_case_zz_x"
    package.mkdir(parents=True)
    (package / "adapter.py").write_text("class Real:\n    pass\n", encoding="utf-8")
    args = cli.build_parser().parse_args(["claim", "cand-1", "--adapter-name", "cold_case_zz_x"])

    with pytest.raises(scaffold.ScaffoldRefusal, match="already exists"):
        cli._claim(args, repo, tmp_path / "drafts")

    assert not (tmp_path / "drafts" / "cold_case_zz_x" / "lease.json").exists()


# --- the directory the prune is allowed to delete in ---


def test_a_fixture_directory_this_pipeline_did_not_write_is_never_pruned(
    tmp_path: Path,
) -> None:
    """`--adapter-name fdle` would have deleted eleven tracked FDLE fixtures.

    Nothing upstream covers this: the generator's overwrite refusal guards the files
    it WRITES, and tests/fixtures/<adapter> is not one of them.
    """
    draft_dir = tmp_path / "drafts" / "fdle"
    (draft_dir / "fixtures").mkdir(parents=True)
    (draft_dir / "fixtures" / "listing_1.html").write_text("ours", encoding="utf-8")
    curated = tmp_path / "repo" / "tests" / "fixtures" / "fdle"
    curated.mkdir(parents=True)
    for name in ("fdle_case.html", "fdle_listing.html"):
        (curated / name).write_text("another suite's evidence", encoding="utf-8")

    with pytest.raises(cli.CliRefusal) as caught:
        cli._copy_fixtures(draft_dir, tmp_path / "repo", "fdle", ["listing_1.html"])

    message = str(caught.value)
    assert "did not write it" in message
    # Both ways to be here, because the advice differs: an unrelated suite's fixtures
    # mean pick another name, a shipped adapter's mean keep the name and deal with the
    # directory deliberately.
    assert "another `--adapter-name`" in message
    assert "re-drafting an adapter that has already shipped" in message
    assert sorted(entry.name for entry in curated.iterdir()) == [
        "fdle_case.html",
        "fdle_listing.html",
    ]


@pytest.mark.parametrize(
    "name",
    [
        "fdle",
        "scout",
        "html",
        "xml",
        "cold_case_ar_asp",
        "cold_case_mn_bca",
        "cold_case_nh_doj",
        "cold_case_ok_osbi",
    ],
)
def test_existing_unowned_fixture_directories_are_refused(name: str, tmp_path: Path) -> None:
    """A capture directory must not be overwritten, even without private fixtures."""
    directory = tmp_path / "tests" / "fixtures" / name
    directory.mkdir(parents=True)
    evidence = directory / "synthetic.html"
    evidence.write_text("<p>Invented evidence</p>")
    with pytest.raises(cli.CliRefusal, match="did not write it"):
        cli._require_a_fixtures_directory_this_pipeline_owns(directory, name)
    assert evidence.read_text() == "<p>Invented evidence</p>"


def test_a_symlinked_fixture_directory_is_refused_rather_than_followed(
    tmp_path: Path,
) -> None:
    """mkdir(exist_ok=True) succeeds on it, iterdir() follows it, unlink() then
    deletes the real files at the far end."""
    elsewhere = tmp_path / "curated"
    elsewhere.mkdir()
    (elsewhere / "someone_elses.html").write_text("evidence", encoding="utf-8")
    # Marked as ours, so the ownership check would WAVE THIS THROUGH: it is the
    # symlink refusal and nothing else that stops the walk from following the link.
    (elsewhere / cli.FIXTURES_MARKER).write_text("ours", encoding="utf-8")
    target = tmp_path / "repo" / "tests" / "fixtures" / "cold_case_zz_x"
    target.parent.mkdir(parents=True)
    target.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(cli.CliRefusal, match="symlink"):
        cli._require_a_fixtures_directory_this_pipeline_owns(target, "cold_case_zz_x")

    assert (elsewhere / "someone_elses.html").is_file()


def test_a_symlinked_marker_is_not_evidence_that_the_directory_is_ours(
    tmp_path: Path,
) -> None:
    """is_file() follows the link, so any existing file could have stood in for it."""
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    (draft_dir / "fixtures").mkdir(parents=True)
    (draft_dir / "fixtures" / "listing_1.html").write_text("ours", encoding="utf-8")
    target = tmp_path / "repo" / "tests" / "fixtures" / "cold_case_zz_x"
    target.mkdir(parents=True)
    (target / "curated.html").write_text("another suite's evidence", encoding="utf-8")
    elsewhere = tmp_path / "somewhere_else.txt"
    elsewhere.write_text("any file at all", encoding="utf-8")
    (target / cli.FIXTURES_MARKER).symlink_to(elsewhere)

    with pytest.raises(cli.CliRefusal, match="symlink"):
        cli._copy_fixtures(draft_dir, tmp_path / "repo", "cold_case_zz_x", ["listing_1.html"])

    assert (target / "curated.html").is_file()
    assert elsewhere.is_file()


def test_a_captured_page_named_like_the_marker_is_refused(tmp_path: Path) -> None:
    """Copying it would overwrite the directory's own ownership evidence."""
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    (draft_dir / "fixtures").mkdir(parents=True)
    (draft_dir / "fixtures" / cli.FIXTURES_MARKER).write_text("a page", encoding="utf-8")

    with pytest.raises(cli.CliRefusal, match=cli.FIXTURES_MARKER):
        _copy(draft_dir, tmp_path / "repo", [cli.FIXTURES_MARKER])

    # Nothing was written: the refusal is ahead of the mkdir.
    assert not (tmp_path / "repo" / "tests").exists()


def test_a_fixture_path_that_is_a_file_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "fixtures" / "cold_case_zz_x"
    target.parent.mkdir(parents=True)
    target.write_text("not a directory", encoding="utf-8")
    with pytest.raises(cli.CliRefusal, match="not a directory"):
        cli._require_a_fixtures_directory_this_pipeline_owns(target, "cold_case_zz_x")


def test_two_captured_pages_with_the_same_basename_are_one_fixture(tmp_path: Path) -> None:
    """The generator flattens the same way, so the count printed must flatten too."""
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    (draft_dir / "fixtures").mkdir(parents=True)
    (draft_dir / "fixtures" / "x.html").write_text("one page", encoding="utf-8")

    assert _copy(draft_dir, tmp_path / "repo", ["a/x.html", "b/x.html"]) == (1, 0)


def test_a_prune_that_cannot_delete_refuses_and_says_a_re_run_finishes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one file-deleting path in the module must not report itself as a traceback."""
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    (draft_dir / "fixtures").mkdir(parents=True)
    repo_root = tmp_path / "repo"
    for name in ("listing_1.html", "listing_2.html"):
        (draft_dir / "fixtures" / name).write_text(name, encoding="utf-8")
    assert _copy(draft_dir, repo_root, ["listing_1.html", "listing_2.html"]) == (2, 0)

    real_unlink = Path.unlink

    def refuse(self: Path, *args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", refuse)
    with pytest.raises(cli.CliRefusal) as caught:
        _copy(draft_dir, repo_root, ["listing_1.html"])

    assert cli.stage_of(caught.value) == "cli"  # not a traceback with no stage on it
    monkeypatch.setattr(Path, "unlink", real_unlink)
    target = repo_root / "tests" / "fixtures" / "cold_case_zz_x"
    assert (target / "listing_1.html").is_file()  # the copies ran first
    # And the re-run the message asks for finishes the prune.
    assert _copy(draft_dir, repo_root, ["listing_1.html"]) == (1, 1)
    assert sorted(entry.name for entry in target.iterdir()) == [
        cli.FIXTURES_MARKER,
        "listing_1.html",
    ]


# --- the adapter argument, before anything makes a path of it ---


@pytest.mark.parametrize("command", ["scaffold", "draft", "verify", "finish"])
def test_a_traversing_adapter_argument_is_refused_on_every_subcommand(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`scaffold ..` pruned every file directly under tests/. Nothing checked it."""
    planted = tmp_path / "tests" / "conftest.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("the repository's own conftest", encoding="utf-8")

    assert cli.main(["--repo-root", str(tmp_path), command, ".."]) == 1

    err = capsys.readouterr().err
    assert "FAIL [cli]" in err
    # The refusal has to be THIS one. Without the check, `..` gets as far as a
    # missing lease and refuses for that instead -- which is the absence of a file
    # rather than a guard, and is exactly how this hole stayed open.
    assert "not a Python identifier in the house form" in err
    assert planted.is_file()


@pytest.mark.parametrize("name", ["..", "", "Cold_Case", "cold case", "a" * 65, "x\n"])
def test_the_adapter_argument_takes_capture_s_own_rule(name: str) -> None:
    with pytest.raises(cli.CliRefusal):
        cli._checked_adapter(name)


def test_a_well_formed_adapter_argument_passes() -> None:
    assert cli._checked_adapter("cold_case_zz_x") == "cold_case_zz_x"


def test_the_deleting_function_checks_the_name_itself(tmp_path: Path) -> None:
    """tests/fixtures/.. is tests/. The prune must not rely on its caller."""
    draft_dir = tmp_path / "drafts" / "x"
    (draft_dir / "fixtures").mkdir(parents=True)
    planted = tmp_path / "repo" / "tests" / "conftest.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("the repository's own conftest", encoding="utf-8")

    with pytest.raises(cli.CliRefusal, match="house form"):
        cli._copy_fixtures(draft_dir, tmp_path / "repo", "..", [])

    assert planted.is_file()


def test_a_package_directory_without_its_adapter_module_is_refused(tmp_path: Path) -> None:
    """The run-book says to delete the package; an operator who deleted only the stub
    used to pass pre-flight and fail later."""
    _write_scaffold(tmp_path, "cold_case_zz_x")
    (tmp_path / loop.ADAPTER_PACKAGE_ROOT / "cold_case_zz_x" / "adapter.py").unlink()
    with pytest.raises(cli.CliRefusal, match="adapter.py"):
        cli._require_the_scaffold(tmp_path, "cold_case_zz_x")


# --- what the live check's guard is allowed to swallow ---


def test_a_defect_in_the_comparison_is_not_reported_as_a_failed_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard covers the fetch. Our own code below it must fail loudly instead of
    degrading the check to permanently-unknown."""
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, url, "0" * 64)

    class _Broken(_LiveClient):
        def get(self, url: str) -> Any:
            self.requested.append(url)
            return object()  # no .content, no .status_code

    held = _Broken()
    _live_client(monkeypatch, held)

    with pytest.raises(AttributeError):
        cli._source_drift_check(tmp_path, _measured(index_url=url), 5)
    assert held.closed is True  # the finally still ran


def test_a_client_that_outlives_a_failed_budget_is_still_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """factory() succeeded, RequestBudget() did not: the client would otherwise leak."""
    url = "https://example.invalid/cold-cases"
    _manifest(tmp_path, url, "0" * 64)
    held = _LiveClient(body=b"x")
    _live_client(monkeypatch, held)

    def explode(client: Any, limit: int) -> Any:
        raise ValueError("a request budget cannot be negative: -1")

    monkeypatch.setattr(verify, "RequestBudget", explode)

    lines = cli._source_drift_check(tmp_path, _measured(index_url=url), 5)

    assert held.closed is True
    assert "the live fetch FAILED" in " ".join(lines)
    assert not [line for line in lines if "budgeted request(s) used" in line]
