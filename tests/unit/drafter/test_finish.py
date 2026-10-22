"""What the finishing pass must never get wrong.

Three of these tests exist because a pull request is a PUBLIC artefact and the verify
report it is built from holds unredacted pytest output; three more exist because the
worktree, the lease and the registry are all state a failed run can strand. The rest
pin the four-way verdict classification, which is the only thing standing between a
reviewer and a green-looking draft nobody verified.

Nothing here spawns anything. The package's autouse guard permits ``git`` and this
interpreter running ``-m pytest`` and refuses everything else, and ``gh`` is not on
that list on purpose, so every test that reaches a command injects a runner.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import finish, lease, loop, scaffold, verify, workspace
from casesignal.scout import registry as scout_registry
from casesignal.scout.models import Candidate, Channel, Level, Status

# --- fixtures for the reports the pass consumes ---


def _reports(
    status: verify.VerifyStatus,
) -> tuple[loop.LoopReport, verify.VerifyReport]:
    loop_report = loop.LoopReport(
        rounds=[loop.RoundOutcome(0, False, "sig-a", False), loop.RoundOutcome(1, True, "", False)],
        passed=status is not verify.VerifyStatus.FAIL,
        stopped_because="green",
    )
    verify_report = verify.VerifyReport(
        status=status,
        invariants=verify.TestOutcome(passed=True, failures=[], raw=""),
        expectations=verify.TestOutcome(passed=True, failures=[], raw=""),
        todos=[verify.Todo(field="county", line=42, text="TODO(county): x")],
        coverage={"victim_age": 0.92},
    )
    return loop_report, verify_report


class _Proc:
    """A CompletedProcess-shaped stand-in for one injected command."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Runner:
    """Records every command and answers from a per-program script.

    The two branch-guard queries answer with an ordinary feature branch and an ordinary
    remote default, so a test that is not ABOUT the guard passes through it. A test that
    is about the guard overrides ``git_rev_parse`` or ``git_symbolic_ref``.
    """

    _DEFAULTS = {
        "git_rev_parse": _Proc(stdout="draft/cold-case-ok-osbi\n"),
        "git_symbolic_ref": _Proc(stdout="origin/main\n"),
    }

    def __init__(self, **script: _Proc) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.script = script

    def __call__(self, cmd: Any, **kwargs: Any) -> _Proc:
        self.calls.append(list(cmd))
        self.kwargs.append(dict(kwargs))
        if cmd[0] == "gh":
            # `gh pr create` and `gh pr view` differ at cmd[2], not cmd[1].
            subcommand = cmd[2] if len(cmd) > 2 else ""
            if f"gh_{subcommand}" in self.script:
                return self.script[f"gh_{subcommand}"]
            if "gh" in self.script:
                return self.script["gh"]
            if subcommand == "view":
                return _Proc(returncode=1, stderr="no pull requests found for branch")
            return _Proc(stdout="https://github.com/o/r/pull/9\n")
        key = f"{cmd[0]}_{cmd[1]}".replace("-", "_")
        if key in self.script:
            return self.script[key]
        return self._DEFAULTS.get(key, _Proc())

    def cmds(self, *head: str) -> list[list[str]]:
        return [call for call in self.calls if call[: len(head)] == list(head)]


def _workspace(tmp_path: Path) -> workspace.Workspace:
    return workspace.Workspace(branch="feat/x", path=tmp_path / "wt", repo_root=tmp_path)


def _finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: verify.VerifyStatus = verify.VerifyStatus.PASS,
    applied: list[str] | None = None,
    runner: _Runner | None = None,
    brief: dict[str, Any] | None = None,
    registry_path: Path | None = None,
) -> tuple[str, _Runner, Path]:
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    ready = ["src/x.py"] if applied is None else list(applied)
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: list(ready))
    monkeypatch.setattr(workspace, "destroy", lambda ws: None)
    loop_report, verify_report = _reports(status)
    used = runner or _Runner()
    url = finish.finish(
        ws=_workspace(tmp_path),
        brief=brief or {"adapter_name": "cold_case_ok_osbi"},
        loop_report=loop_report,
        verify_report=verify_report,
        draft_dir=draft_dir,
        registry_path=registry_path or (tmp_path / "registry.yaml"),
        runner=used,
    )
    return url, used, draft_dir


# --- the title ---


def test_title_names_a_failing_draft() -> None:
    assert "FAIL" in finish.build_pr_title("cold_case_ok_osbi", verify.VerifyStatus.FAIL)


def test_title_is_clean_for_a_passing_draft() -> None:
    title = finish.build_pr_title("cold_case_ok_osbi", verify.VerifyStatus.PASS)
    assert "FAIL" not in title and "cold_case_ok_osbi" in title


def test_title_distinguishes_a_draft_that_only_passed_with_todos() -> None:
    """PASS and PASS_WITH_TODOS must not read the same in a list of pull requests."""
    plain = finish.build_pr_title("a", verify.VerifyStatus.PASS)
    todos = finish.build_pr_title("a", verify.VerifyStatus.PASS_WITH_TODOS)
    assert plain != todos and "PASS_WITH_TODOS" in todos


# --- the body ---


def test_body_reports_rounds_todos_and_coverage() -> None:
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS_WITH_TODOS)
    body = finish.build_pr_body(
        {
            "adapter_name": "cold_case_ok_osbi",
            "session_id": "20260831T140211Z-a3f9",
            "records_captured": 307,
        },
        loop_report,
        verify_report,
    )
    assert "20260831T140211Z-a3f9" in body
    assert "2 rounds" in body
    assert "TODO(county)" in body
    assert "victim_age" in body
    assert "PASS_WITH_TODOS" in body


def test_body_states_the_draft_is_machine_written() -> None:
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)
    body = finish.build_pr_body({"adapter_name": "a"}, loop_report, verify_report)
    assert "machine draft" in body.lower()


def test_body_never_reproduces_unredacted_failure_text() -> None:
    """The one leak this body could carry, and the reason it renders counts.

    ``TestOutcome.failures`` holds pytest's short summary VERBATIM -- redaction lives
    in ``loop.redact``, on the way into an agent's prompt, not in verify's capture --
    so a golden expectation failure's assertion message carries the value transcribed
    off the source. ``raw`` carries the whole of stdout besides. A pull request is
    public.
    """
    secret = "1998-04-02"
    outcome = verify.TestOutcome(
        passed=False,
        failures=[f"FAILED test_expectations.py::test_incident_date - assert '' == '{secret}'"],
        raw=f"E  AssertionError: assert '' == '{secret}'\n{secret}\n",
        returncode=1,
    )
    report = verify.VerifyReport(
        status=verify.VerifyStatus.FAIL,
        invariants=outcome,
        expectations=outcome,
        todos=[],
        coverage={},
    )
    body = finish.build_pr_body(
        {"adapter_name": "a"},
        loop.LoopReport(rounds=[], passed=False, stopped_because="budget"),
        report,
    )
    assert secret not in body
    assert outcome.failures[0] not in body
    assert "AssertionError" not in body
    assert "test_incident_date" not in body
    assert "1 reported failure(s)" in body


def test_body_says_when_nothing_was_verified_rather_than_just_fail() -> None:
    """The fourth classification. FAIL alone cannot distinguish it, and the fixes differ."""
    never_ran = verify.TestOutcome(passed=False, failures=[], raw="", ran=False, returncode=5)
    report = verify.VerifyReport(
        status=verify.VerifyStatus.FAIL,
        invariants=never_ran,
        expectations=never_ran,
        todos=[],
        coverage={},
    )
    body = finish.build_pr_body(
        {"adapter_name": "a"},
        loop.LoopReport(rounds=[], passed=False, stopped_because="budget"),
        report,
    )
    assert "NOTHING WAS VERIFIED" in body
    assert "not-run" in body
    assert "final verdict not green" in body
    assert "None." in body  # no marked TODOs, said plainly rather than left blank
    # summary() already carries the phrase, so the phrase alone grades nothing here.
    # The callout is the part that says the FIX differs, and that is what is asserted.
    assert "This is not the same failure as a red suite" in body

    green_loop, green_verify = _reports(verify.VerifyStatus.PASS)
    ordinary = finish.build_pr_body({"adapter_name": "a"}, green_loop, green_verify)
    assert "This is not the same failure as a red suite" not in ordinary


def test_a_green_round_reads_as_green() -> None:
    """``passed`` is read FIRST, because a green round's signature is also empty."""
    assert finish.round_reason(loop.RoundOutcome(1, True, "", False)) == "green"


def test_body_does_not_call_a_red_round_with_no_parsed_failures_green() -> None:
    """The empty signature is shared by a green round and a red one that parsed nothing."""
    red_but_silent = loop.RoundOutcome(0, False, "", False)
    assert finish.round_reason(red_but_silent) != "green"
    assert "parsed to no failure lines" in finish.round_reason(red_but_silent)


@pytest.mark.parametrize("signature", loop.RESERVED_SIGNATURES)
def test_body_reads_a_reserved_signature_as_a_condition_not_a_failure_set(signature: str) -> None:
    """All four reserved names mean no test ran; none of them is a set of failing tests."""
    reason = finish.round_reason(loop.RoundOutcome(0, False, signature, False))
    assert reason == f"no test ran ({signature})"


def test_body_labels_coverage_as_the_locators_measurement_not_the_parsers() -> None:
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)
    body = finish.build_pr_body({"adapter_name": "a"}, loop_report, verify_report)
    heading = "### Locator coverage, measured by the inventory pass"
    assert heading in body
    assert "NOT a measurement of the drafted parser" in body


def test_body_carries_no_generator_digest_marker() -> None:
    """A marker line in the body would be a line count and a diffstat nobody meant."""
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)
    body = finish.build_pr_body({"adapter_name": "a"}, loop_report, verify_report)
    assert not any(scaffold.is_marker_line(line) for line in body.splitlines())
    assert "drafted-by:" not in body


# --- stage attribution ---


def test_a_verify_stage_refusal_is_not_attributed_to_the_scaffold_pass() -> None:
    """``UnusableBrief`` IS an ``UnmeasuredBrief`` IS a ``ScaffoldRefusal``.

    An orchestrator whose ``except`` chain is written in declaration order tells the
    operator to re-run the scaffold pass for a refusal the verify pass raised.
    """
    assert issubclass(verify.UnusableBrief, scaffold.ScaffoldRefusal)
    assert finish.refusal_stage(verify.UnusableBrief("x")) == "verify"
    assert finish.refusal_stage(scaffold.UnmeasuredBrief("x")) == "inventory"
    assert finish.refusal_stage(scaffold.ScaffoldRefusal("x")) == "scaffold"


def test_stage_attribution_covers_the_containment_and_lease_refusals() -> None:
    assert finish.refusal_stage(workspace.DeletedInWorkspace(["a"])) == "apply-back"
    assert finish.refusal_stage(workspace.WorkspaceExists("x")) == "workspace"
    assert finish.refusal_stage(loop.BarrierViolation("x")) == "draft"
    assert finish.refusal_stage(ValueError("x")) == "unknown"


# --- the pass ---


def test_finish_writes_an_outcome_record_and_releases_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: ["src/x.py"])
    monkeypatch.setattr(workspace, "destroy", lambda ws: None)

    calls: list[list[str]] = []

    def runner(cmd: Any, **kwargs: Any) -> Any:
        calls.append(list(cmd))

        class P:
            returncode = 0
            stdout = (
                "draft/cold-case-ok-osbi\n"
                if cmd[:2] == ["git", "rev-parse"]
                else "origin/main\n"
                if cmd[:2] == ["git", "symbolic-ref"]
                else "https://github.com/o/r/pull/9\n"
                if cmd[0] == "gh"
                else ""
            )
            stderr = ""

        return P()

    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)
    url = finish.finish(
        ws=workspace.Workspace(branch="feat/x", path=tmp_path, repo_root=tmp_path),
        brief={"adapter_name": "cold_case_ok_osbi"},
        loop_report=loop_report,
        verify_report=verify_report,
        draft_dir=draft_dir,
        registry_path=tmp_path / "registry.yaml",
        runner=runner,
    )

    assert url == "https://github.com/o/r/pull/9"
    assert (draft_dir / "outcome.json").exists()
    assert lease.read(draft_dir) is None
    assert any("gh" in c[0] for c in calls)


def test_finish_publishes_the_body_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``gh`` is handed the file on disk, so what shipped is re-readable afterwards."""
    _url, runner, draft_dir = _finish(tmp_path, monkeypatch)
    (gh,) = runner.cmds("gh")
    body_path = Path(gh[gh.index("--body-file") + 1])
    assert body_path == draft_dir / finish.PR_BODY_FILE
    assert "machine draft" in body_path.read_text().lower()


def test_finish_commits_only_the_paths_it_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``git commit -- <paths>`` is --only mode.

    Without the pathspec, an operator with unrelated work already staged finds it
    inside a machine-drafted commit.
    """
    _url, runner, _draft = _finish(tmp_path, monkeypatch, applied=["src/a.py", "src/b.py"])
    (commit,) = runner.cmds("git", "commit")
    assert commit[-3:] == ["--", "src/a.py", "src/b.py"]
    (add,) = runner.cmds("git", "add")
    assert add == ["git", "add", "--", "src/a.py", "src/b.py"]


def test_finish_never_stages_a_path_outside_the_drafters_own_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scaffold's uncommitted output is picked up; nothing else in the checkout is."""
    parser_module = "src/casesignal/etl/adapters/cold_case_ok_osbi/transform.py"
    status = _Proc(
        stdout="\0".join(
            [
                " M docs/drafts/cold_case_ok_osbi.md",
                "?? src/casesignal/etl/sources/cold_case_ok.yaml",
                f" M {parser_module}",
                " M src/casesignal/api/main.py",
                " M src/casesignal/etl/adapters/cold_case_ok_osbi_EVIL/x.py",
                "",
            ]
        )
    )
    runner = _Runner(git_status=status)
    _url, runner, _draft = _finish(
        tmp_path,
        monkeypatch,
        applied=[parser_module],
        runner=runner,
        brief={"adapter_name": "cold_case_ok_osbi", "state": "OK"},
    )
    (add,) = runner.cmds("git", "add")
    assert add[3:] == [
        "docs/drafts/cold_case_ok_osbi.md",
        parser_module,
        "src/casesignal/etl/sources/cold_case_ok.yaml",
    ]


def test_finish_refuses_when_there_is_nothing_at_all_to_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(finish.NothingDrafted):
        _finish(tmp_path, monkeypatch, applied=[])


def test_a_red_draft_still_opens_a_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a failure is shipped and named, not swallowed."""
    url, runner, draft_dir = _finish(tmp_path, monkeypatch, status=verify.VerifyStatus.FAIL)
    assert url == "https://github.com/o/r/pull/9"
    (gh,) = runner.cmds("gh")
    assert "FAIL" in gh[gh.index("--title") + 1]
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["verify"]["status"] == "FAIL"


def test_the_outcome_record_carries_counts_and_never_the_raw_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _url, _runner, draft_dir = _finish(tmp_path, monkeypatch)
    text = (draft_dir / finish.OUTCOME_FILE).read_text()
    record = json.loads(text)
    assert record["verify"]["invariants"]["failure_count"] == 0
    assert "raw" not in text and "failures" not in text


def test_the_outcome_record_names_the_branch_a_failed_finish_leaves_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``destroy`` keeps the branch, so a second draft collides until someone deletes it."""
    _url, _runner, draft_dir = _finish(tmp_path, monkeypatch)
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["branch"] == "feat/x"
    assert record["worktree"].endswith("wt")


# --- which branch this pass writes to ---


def test_the_push_is_an_ordinary_upstream_push_of_the_current_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The most consequential command in the module, pinned by shape.

    Deleting it, or turning it into anything that names a destination of its own
    (`origin HEAD:main`, `--force`), must not pass.
    """
    _url, runner, _draft = _finish(tmp_path, monkeypatch)
    (push,) = runner.cmds("git", "push")
    assert push == [
        "git",
        "push",
        "--set-upstream",
        "origin",
        "HEAD:refs/heads/draft/cold-case-ok-osbi",
    ]


def test_the_push_happens_only_after_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _url, runner, _draft = _finish(tmp_path, monkeypatch)
    order = [call[:2] for call in runner.calls]
    assert order.index(["git", "commit"]) < order.index(["git", "push"])


def test_finish_refuses_to_commit_onto_the_remote_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`workspace.create` puts the draft branch in the WORKTREE; repo_root never moves.

    So the branch this pass commits and pushes is whichever one the operator is
    standing on. On the default branch that is a machine draft committed to main and
    pushed to origin/main.
    """
    runner = _Runner(git_rev_parse=_Proc(stdout="main\n"))
    with pytest.raises(finish.ProtectedBranch) as caught:
        _finish(tmp_path, monkeypatch, runner=runner)
    assert "main" in str(caught.value)
    assert not runner.cmds("git", "add")
    assert not runner.cmds("git", "commit")
    assert not runner.cmds("git", "push")


def test_finish_refuses_the_remotes_default_even_when_it_is_not_named_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The remote is asked; the answer is not assumed."""
    runner = _Runner(
        git_rev_parse=_Proc(stdout="develop\n"),
        git_symbolic_ref=_Proc(stdout="origin/develop\n"),
    )
    with pytest.raises(finish.ProtectedBranch):
        _finish(tmp_path, monkeypatch, runner=runner)


def test_master_is_refused_even_when_the_remote_cannot_be_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clone that never fetched has no origin/HEAD; the fallbacks still hold."""
    runner = _Runner(
        git_rev_parse=_Proc(stdout="master\n"),
        git_symbolic_ref=_Proc(
            returncode=128, stderr="ref refs/remotes/origin/HEAD is not a symbolic ref"
        ),
    )
    with pytest.raises(finish.ProtectedBranch):
        _finish(tmp_path, monkeypatch, runner=runner)


def test_finish_refuses_a_detached_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _Runner(git_rev_parse=_Proc(stdout="HEAD\n"))
    with pytest.raises(finish.ProtectedBranch) as caught:
        _finish(tmp_path, monkeypatch, runner=runner)
    assert "detached" in str(caught.value).lower() or "not on a named branch" in str(caught.value)


def test_an_ordinary_feature_branch_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard's other direction: it must not refuse the normal case."""
    runner = _Runner(git_rev_parse=_Proc(stdout="draft/cold-case-ok-osbi\n"))
    url, runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


def test_the_guard_runs_before_the_checkout_is_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal must leave the operator's checkout byte-for-byte as it was."""
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    applied_calls: list[str] = []

    def apply_back(ws: workspace.Workspace, allowed: Any) -> list[str]:
        applied_calls.append("called")
        return ["src/x.py"]

    monkeypatch.setattr(workspace, "apply_back", apply_back)
    monkeypatch.setattr(workspace, "destroy", lambda ws: None)
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)
    with pytest.raises(finish.ProtectedBranch):
        finish.finish(
            ws=_workspace(tmp_path),
            brief={"adapter_name": "cold_case_ok_osbi"},
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            registry_path=tmp_path / "registry.yaml",
            runner=_Runner(git_rev_parse=_Proc(stdout="main\n")),
        )
    assert applied_calls == []


def test_the_record_names_the_operators_branch_not_only_the_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The residue after a failed `gh pr create` is a commit on the OPERATOR's branch.

    ``branch`` names the worktree branch that ``destroy`` keeps. It is not what a
    reviewer has to clean up when the commit and the push already went through.
    """
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: ["src/x.py"])
    monkeypatch.setattr(workspace, "destroy", lambda ws: None)
    runner = _Runner(
        git_rev_parse=_Proc(stdout="draft/cold-case-ok-osbi\n"),
        gh=_Proc(returncode=1, stderr="gh: not authenticated"),
    )
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)
    with pytest.raises(finish.CommandFailed):
        finish.finish(
            ws=_workspace(tmp_path),
            brief={"adapter_name": "cold_case_ok_osbi"},
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            registry_path=tmp_path / "registry.yaml",
            runner=runner,
        )
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["branch"] == "feat/x"
    assert record["committed_to"] == "draft/cold-case-ok-osbi"
    assert record["pushed"] is True
    assert any(
        "machine-drafted commit on 'draft/cold-case-ok-osbi'" in w for w in record["warnings"]
    )


def test_a_clean_run_records_no_residue_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The residue warning belongs to the ERROR path only.

    On a run that opened its pull request there is no residue, and a record that says
    there is sends a reviewer looking for a commit nobody has to clean up.
    """
    _url, _runner, draft_dir = _finish(tmp_path, monkeypatch)
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["committed_to"] == "draft/cold-case-ok-osbi"
    assert record["pushed"] is True
    assert not any("machine-drafted commit on" in w for w in record["warnings"])


def test_nothing_is_recorded_as_committed_when_the_commit_never_happened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _Runner(
        git_commit=_Proc(returncode=1, stderr="pre-commit hook refused"),
        git_diff=_Proc(returncode=1),
    )
    with pytest.raises(finish.CommandFailed):
        _finish(tmp_path, monkeypatch, runner=runner)
    record = json.loads((tmp_path / "draft" / finish.OUTCOME_FILE).read_text())
    assert record["committed_to"] == ""
    assert record["pushed"] is False


# --- a refusal must not destroy the draft ---


def test_a_protected_branch_refusal_leaves_the_draft_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario the guard exists for must not cost the drafted adapter.

    Nothing ever commits inside the worktree, and `destroy` is
    `git worktree remove --force`, so a refusal raised from inside the try block would
    force-delete the whole agent-written draft and leave a branch byte-identical to
    main. The bill for re-drafting is a real agent session on a self-funded project.
    """
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    destroyed: list[str] = []
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: ["src/x.py"])
    monkeypatch.setattr(workspace, "destroy", lambda ws: destroyed.append(ws.branch))
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)

    with pytest.raises(finish.ProtectedBranch) as caught:
        finish.finish(
            ws=_workspace(tmp_path),
            brief={"adapter_name": "cold_case_ok_osbi"},
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            registry_path=tmp_path / "registry.yaml",
            runner=_Runner(git_rev_parse=_Proc(stdout="main\n")),
        )

    assert destroyed == []
    assert lease.read(draft_dir) is not None
    assert not (draft_dir / finish.OUTCOME_FILE).exists()
    assert "NOTHING HAS BEEN TOUCHED" in str(caught.value)


def test_a_preflight_refusal_is_not_attributed_to_the_finish_stage(
    tmp_path: Path,
) -> None:
    """Telling the orchestrator "finish" sends the operator to re-run what cannot help."""
    assert finish.refusal_stage(finish.ProtectedBranch("x")) == "pre-flight"
    assert finish.refusal_stage(finish.UnusableBriefForFinish("x")) == "pre-flight"
    assert finish.refusal_stage(finish.NothingDrafted("x")) == "finish"


def test_a_brief_with_no_adapter_name_is_refused_by_name_not_by_key_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured through `finish`, not through a helper one call site earlier.

    `loop.default_allowed_paths` subscripts `brief['adapter_name']`, so a raw brief put
    a bare KeyError inside the try block, which `refusal_stage` reported as "unknown".
    """
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    destroyed: list[str] = []
    monkeypatch.setattr(workspace, "destroy", lambda ws: destroyed.append(ws.branch))
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)

    with pytest.raises(finish.UnusableBriefForFinish):
        finish.finish(
            ws=_workspace(tmp_path),
            brief={"session_id": "s"},
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            registry_path=tmp_path / "registry.yaml",
            runner=_Runner(),
        )

    assert destroyed == []
    assert lease.read(draft_dir) is not None


def test_the_worktree_is_kept_when_apply_back_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal leaves the changes in the worktree, so removing it destroys them."""
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    destroyed: list[str] = []

    def refuse(ws: workspace.Workspace, allowed: Any) -> list[str]:
        raise workspace.DisallowedWrite(["src/casesignal/api/main.py"])

    monkeypatch.setattr(workspace, "apply_back", refuse)
    monkeypatch.setattr(workspace, "destroy", lambda ws: destroyed.append(ws.branch))
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)

    with pytest.raises(workspace.DisallowedWrite):
        finish.finish(
            ws=_workspace(tmp_path),
            brief={"adapter_name": "cold_case_ok_osbi"},
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            registry_path=tmp_path / "registry.yaml",
            runner=_Runner(),
        )

    assert destroyed == []
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["worktree_kept"] is True
    kept = [w for w in record["warnings"] if "was KEPT" in w]
    assert kept and "apply-back refused" in kept[0]
    # git refuses to delete a branch a live worktree is using, so the order matters.
    assert kept[0].index("git worktree remove") < kept[0].index("git branch -D")
    assert lease.read(draft_dir) is None


def test_a_clean_worktree_is_still_destroyed_on_a_successful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`applied == []` is not "the draft is stranded"; it is "there was nothing there".

    apply_back RETURNING an empty list is a completed survey of a clean worktree. The
    run can still succeed, because the scaffold's own output in the checkout is
    stageable. Reading the empty list as a refusal kept a worktree that held nothing,
    told the operator it held "the only copy of the draft", and left the branch behind
    so the NEXT draft of the same adapter was refused with WorkspaceExists.
    """
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    destroyed: list[str] = []
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: [])
    monkeypatch.setattr(workspace, "destroy", lambda ws: destroyed.append(ws.branch))
    runner = _Runner(
        git_status=_Proc(stdout="\0".join([" M docs/drafts/cold_case_ok_osbi.md", ""]))
    )
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)

    url = finish.finish(
        ws=_workspace(tmp_path),
        brief={"adapter_name": "cold_case_ok_osbi"},
        loop_report=loop_report,
        verify_report=verify_report,
        draft_dir=draft_dir,
        registry_path=tmp_path / "registry.yaml",
        runner=runner,
    )

    assert url == "https://github.com/o/r/pull/9"
    assert destroyed == ["feat/x"]
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["applied_paths"] == []
    assert record["staged_paths"] == ["docs/drafts/cold_case_ok_osbi.md"]
    assert record["worktree_kept"] is False
    assert not any("was KEPT" in warning for warning in record["warnings"])


def test_a_preflight_query_that_fails_says_the_lease_is_still_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All three pre-flight refusals keep the lease, which departs from the plan.

    The plan says the lease is released in a finally. Pre-flight runs before that
    finally exists, deliberately, because the draft is still live in its worktree and
    the lease is what stops a second run drafting over it. An operator should not have
    to infer that, nor how to clear it.
    """
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    destroyed: list[str] = []
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: ["src/x.py"])
    monkeypatch.setattr(workspace, "destroy", lambda ws: destroyed.append(ws.branch))
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)

    with pytest.raises(finish.PreflightFailed) as caught:
        finish.finish(
            ws=_workspace(tmp_path),
            brief={"adapter_name": "cold_case_ok_osbi"},
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            registry_path=tmp_path / "registry.yaml",
            runner=_Runner(git_rev_parse=_Proc(returncode=128, stderr="not a git repository")),
        )

    assert finish.refusal_stage(caught.value) == "pre-flight"
    assert "--force" in str(caught.value)
    assert "still HELD" in str(caught.value)
    assert destroyed == []
    assert lease.read(draft_dir) is not None
    assert not (draft_dir / finish.OUTCOME_FILE).exists()


@pytest.mark.parametrize(
    "refusal",
    [
        finish.PreflightFailed("x"),
        finish.ProtectedBranch("x"),
        finish.UnusableBriefForFinish("x"),
    ],
)
def test_every_preflight_refusal_is_attributed_to_pre_flight(refusal: Exception) -> None:
    assert finish.refusal_stage(refusal) == "pre-flight"


def test_every_preflight_message_names_the_escape_hatch() -> None:
    """One sentence, one place, so the three refusals cannot drift apart."""
    assert "lease.json" in finish.PREFLIGHT_UNTOUCHED
    assert "still HELD" in finish.PREFLIGHT_UNTOUCHED


def test_deleting_the_lease_file_is_a_remedy_that_actually_works(tmp_path: Path) -> None:
    """The prescribed remedy, executed. A message naming a remedy nobody tested is
    how the last one got written."""
    draft_dir = tmp_path / "drafts" / "cold_case_zz_x"
    lease.acquire(draft_dir, "cold_case_zz_x", "draft/cold_case_zz_x")
    with pytest.raises(lease.LeaseHeld):
        lease.acquire(draft_dir, "cold_case_zz_x", "draft/cold_case_zz_x")

    assert "data/drafts/<adapter>/lease.json" in finish.PREFLIGHT_UNTOUCHED
    (draft_dir / "lease.json").unlink()

    held = lease.acquire(draft_dir, "cold_case_zz_x", "draft/cold_case_zz_x")
    assert held.adapter_name == "cold_case_zz_x"


# --- which names count as protected ---


def test_a_protected_branch_is_matched_case_insensitively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout on Windows or macOS is case-insensitive; `Main` IS `main` there."""
    for spelling in ("Main", "MAIN", "Master"):
        with pytest.raises(finish.ProtectedBranch):
            _finish(
                tmp_path / spelling,
                monkeypatch,
                runner=_Runner(git_rev_parse=_Proc(stdout=f"{spelling}\n")),
            )


def test_a_repository_can_protect_its_own_branches_through_git_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No new dependency, no network, no auth scope: a config key, unioned in."""
    runner = _Runner(
        git_rev_parse=_Proc(stdout="integration\n"),
        git_config=_Proc(stdout="integration\nstaging\n"),
    )
    with pytest.raises(finish.ProtectedBranch):
        _finish(tmp_path, monkeypatch, runner=runner)


def test_an_operator_can_protect_a_branch_for_one_run_through_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No space after the comma: whitespace splitting alone yields one name,
    # "integration,staging", which matches nothing. The comma handling is what makes
    # this refuse, so the fixture grades it.
    monkeypatch.setenv(finish.PROTECTED_BRANCH_ENV, "integration,staging")
    runner = _Runner(git_rev_parse=_Proc(stdout="staging\n"))
    with pytest.raises(finish.ProtectedBranch):
        _finish(tmp_path, monkeypatch, runner=runner)
    assert finish._split_names("a, b  c,d") == ["a", "b", "c", "d"]


def test_a_config_value_that_cannot_be_a_branch_name_is_not_a_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three of the four sources are free text, so a mangled entry must not become a rule."""
    assert finish.is_branch_name("feat/x") and finish.is_branch_name("release/1.0")
    assert not finish.is_branch_name("https://github.com/o/r/pull/9")
    assert not finish.is_branch_name("a b")
    assert not finish.is_branch_name("x..y")
    # A name with whitespace never reaches is_branch_name -- _split_names has already
    # broken it into two. The fixture is a single token git could not accept.
    runner = _Runner(
        git_config=_Proc(stdout="a:b\n"),
    )
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


# --- what gh printed, and what it means ---


def test_a_release_notice_after_the_url_is_not_mistaken_for_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gh` prints more than the URL, and the last non-empty line is often prose.

    Returning that prose would put `drafted: PR ! A new release of gh...` into the
    registry note and `outcome.json:pr_url`. Refusing "" for an un-created pull
    request and then returning a sentence for one is the same defect one step along.
    """
    runner = _Runner(
        gh_create=_Proc(
            stdout=(
                "https://github.com/o/r/pull/9\n"
                "\n"
                "! A new release of gh is available: 2.60.0 -> 2.61.0\n"
                "To learn more, visit gh help\n"
            )
        )
    )
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


def test_gh_printing_only_prose_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _Runner(gh_create=_Proc(stdout="To learn more, visit gh help\n"))
    with pytest.raises(finish.FinishRefusal):
        _finish(tmp_path, monkeypatch, runner=runner)


def test_a_rerun_adopts_the_pull_request_that_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary shape of a re-run, and `_commit` already takes this trouble.

    Registry write failed, operator re-ran: the commit is benign, the push a no-op,
    and the only thing left is a pull request that already exists. Recording that as
    pr_url:"" with a failed run, while the pull request sits there, is a false report.
    """
    runner = _Runner(
        gh_create=_Proc(returncode=1, stderr="a pull request for branch already exists"),
        gh_view=_Proc(
            stdout=json.dumps(
                {
                    "url": "https://github.com/o/r/pull/9",
                    "headRefName": "draft/cold-case-ok-osbi",
                    "state": "OPEN",
                    "body": "<!-- casesignal-adapter:cold_case_ok_osbi -->",
                }
            )
        ),
    )
    url, runner, draft_dir = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert any("updated the existing adapter pull request" in w for w in record["warnings"])
    assert any(c[:3] == ["gh", "pr", "edit"] and "--body-file" in c for c in runner.calls)


def test_a_gh_failure_with_no_existing_pull_request_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery must not swallow an unrelated failure, e.g. a bad token."""
    runner = _Runner(
        gh_create=_Proc(returncode=1, stderr="gh: not authenticated"),
        gh_view=_Proc(returncode=1, stderr="no pull requests found for branch"),
    )
    with pytest.raises(finish.CommandFailed) as caught:
        _finish(tmp_path, monkeypatch, runner=runner)
    assert "not authenticated" in str(caught.value)


def test_a_gh_view_that_names_no_pull_request_does_not_invent_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gh pr view` can exit 0 and still not name a pull request.

    The other side of the recovery from the failure path above, where `gh pr view`
    exited non-zero and the CommandFailed handler answered first. Here it succeeds and
    says nothing useful, and a URL invented at that point would be written to
    outcome.json and into the registry note as a link to a pull request nobody opened.
    """
    runner = _Runner(
        gh_create=_Proc(returncode=1, stderr="gh: not authenticated"),
        gh_view=_Proc(stdout="\n"),
    )
    with pytest.raises(finish.CommandFailed) as caught:
        _finish(tmp_path, monkeypatch, runner=runner)
    assert "not authenticated" in str(caught.value)


def test_parser_allowed_paths_does_not_subscript_the_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt and braces behind the pre-flight refusal, and the one call site that used
    to put a bare KeyError inside the try block."""
    assert finish.parser_allowed_paths({}) == finish.parser_allowed_paths({"adapter_name": ""})
    assert finish.parser_allowed_paths({"adapter_name": "a"}) == ["src/casesignal/etl/adapters/a"]


def test_an_unset_protected_branch_config_key_is_the_ordinary_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git config --get-all` exits 1 when the key is simply not set."""
    runner = _Runner(git_config=_Proc(returncode=1))
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


def test_draft_owned_paths_reads_a_brief_the_way_every_other_reader_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A brief missing adapter_name must not raise KeyError from inside the try block.

    It would be recorded as stage "unknown", which attributes a caller's bad brief to
    nothing at all.
    """
    assert finish.draft_owned_paths({}) == finish.draft_owned_paths({"adapter_name": None})
    assert any("(unnamed)" in path for path in finish.draft_owned_paths({}))


# --- cleanup that a failure must not skip ---


def test_a_failed_pull_request_keeps_the_lease_and_worktree_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: ["src/x.py"])
    destroyed: list[str] = []
    monkeypatch.setattr(workspace, "destroy", lambda ws: destroyed.append(ws.branch))
    runner = _Runner(gh=_Proc(returncode=1, stderr="gh: not authenticated"))
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)

    with pytest.raises(finish.CommandFailed):
        finish.finish(
            ws=_workspace(tmp_path),
            brief={"adapter_name": "cold_case_ok_osbi"},
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            registry_path=tmp_path / "registry.yaml",
            runner=runner,
        )

    assert destroyed == []
    assert lease.read(draft_dir) is not None
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["worktree_kept"] is True
    assert record["pr_url"] == ""
    assert record["error"]["stage"] == "finish"
    assert record["error"]["type"] == "CommandFailed"


def test_a_worktree_that_will_not_die_does_not_strand_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup steps are guarded individually; one failing must not skip the others."""
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: ["src/x.py"])

    def explode(ws: workspace.Workspace) -> None:
        raise RuntimeError("git worktree remove failed: locked")

    monkeypatch.setattr(workspace, "destroy", explode)
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)
    url = finish.finish(
        ws=_workspace(tmp_path),
        brief={"adapter_name": "cold_case_ok_osbi"},
        loop_report=loop_report,
        verify_report=verify_report,
        draft_dir=draft_dir,
        registry_path=tmp_path / "registry.yaml",
        runner=_Runner(),
    )

    assert url == "https://github.com/o/r/pull/9"
    assert lease.read(draft_dir) is None
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert any("was not removed" in warning for warning in record["warnings"])
    assert any("git branch -D feat/x" in warning for warning in record["warnings"])


def test_the_default_runner_is_resolved_through_the_module_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default captured at definition time walks past the package's spawn guard.

    ``gh`` is not on the guard's allowlist, so a defaulted call that bypassed the
    patch would try to execute the real binary.
    """
    draft_dir = tmp_path / "draft"
    lease.acquire(draft_dir, "cold_case_ok_osbi", "draft/cold-case-ok-osbi")
    monkeypatch.setattr(workspace, "apply_back", lambda ws, allowed: ["src/x.py"])
    monkeypatch.setattr(workspace, "destroy", lambda ws: None)
    runner = _Runner()
    monkeypatch.setattr(subprocess, "run", runner)
    loop_report, verify_report = _reports(verify.VerifyStatus.PASS)

    url = finish.finish(
        ws=_workspace(tmp_path),
        brief={"adapter_name": "cold_case_ok_osbi"},
        loop_report=loop_report,
        verify_report=verify_report,
        draft_dir=draft_dir,
        registry_path=tmp_path / "registry.yaml",
    )

    assert url == "https://github.com/o/r/pull/9"
    assert runner.cmds("gh")


def test_a_checkout_git_cannot_read_is_a_warning_not_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Picking up the scaffold's uncommitted output is a completeness improvement.

    Losing it costs a reviewer a follow-up push. It must not cost the pull request.
    """
    runner = _Runner(git_status=_Proc(returncode=128, stderr="not a git repository"))
    url, runner, draft_dir = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert any("could not list" in warning for warning in record["warnings"])


def test_a_commit_with_nothing_staged_is_benign_rather_than_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-run over paths already committed must still open the pull request.

    The two cases are told apart by asking git -- ``git diff --cached --quiet``
    exits 0 when nothing is staged -- rather than by matching its prose, which is
    locale-dependent.
    """
    runner = _Runner(
        git_commit=_Proc(returncode=1, stderr="nothing to commit, working tree clean"),
        git_diff=_Proc(returncode=0),
    )
    url, runner, draft_dir = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"
    assert runner.cmds("git", "diff")
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert any("already committed" in warning for warning in record["warnings"])


def test_a_commit_that_really_failed_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the probe: staged changes plus a non-zero exit is a failure."""
    runner = _Runner(
        git_commit=_Proc(returncode=1, stderr="pre-commit hook refused"),
        git_diff=_Proc(returncode=1),
    )
    with pytest.raises(finish.CommandFailed):
        _finish(tmp_path, monkeypatch, runner=runner)


def test_a_warning_before_the_url_is_not_mistaken_for_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``gh`` prefaces the URL with warnings often enough that the first line is wrong."""
    runner = _Runner(
        gh=_Proc(stdout="Warning: 3 uncommitted changes\nhttps://github.com/o/r/pull/9\n")
    )
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


def test_a_bare_non_pull_request_url_is_not_mistaken_for_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The noise on the OTHER side of the answer, on its own line and a real URL.

    A "See https://..." footer never reached the shape check: it does not START with
    http, so the first filter already dropped it. A bare non-pull-request URL does
    reach it, leaves two candidates, and makes any position in the output the wrong
    answer.
    """
    runner = _Runner(
        gh_create=_Proc(
            stdout=("https://github.com/o/r/pull/9\nhttps://github.com/o/r/actions/runs/12345\n")
        )
    )
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


def test_prose_naming_a_pull_request_path_is_not_a_second_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real `gh` output shape: a URL line, a blank line, and a line of prose.

    This grades the "line starts with http" filter, which the `/pull/` filter cannot
    stand in for. Once the URL TOKEN is extracted rather than the whole line, the
    filter's job is to guarantee every line reaching the tokeniser actually has a
    token -- and gh separates its URL from its footer with a blank line.
    """
    runner = _Runner(
        gh_create=_Proc(
            stdout=(
                "https://github.com/o/r/pull/9\n"
                "\n"
                "See https://github.com/o/r/pull/9/checks for the checks\n"
            )
        )
    )
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"
    # Stated directly as well, because the two filters now protect different things
    # and the end-to-end assertion above cannot say which one did the work: the blank
    # line has no token to extract, and the prose line is not a URL.
    assert finish._urls_in("https://x/pull/1\n\nSee https://x/pull/2 here\n") == [
        "https://x/pull/1"
    ]


def test_a_status_word_after_the_url_is_not_part_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line is still not a URL. Returning it whole put `(created)` into the record."""
    runner = _Runner(gh_create=_Proc(stdout="https://github.com/o/r/pull/9 (created)\n"))
    url, _runner, draft_dir = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["pr_url"] == "https://github.com/o/r/pull/9"


def test_the_same_url_printed_twice_is_one_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ambiguity is two DIFFERENT pull requests, not one echoed twice."""
    runner = _Runner(
        gh_create=_Proc(stdout="https://github.com/o/r/pull/9\nhttps://github.com/o/r/pull/9\n")
    )
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


def test_two_pull_request_urls_are_ambiguous_and_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guessing which one is it would put the wrong link in the registry and the record."""
    runner = _Runner(
        gh_create=_Proc(stdout="https://github.com/o/r/pull/8\nhttps://github.com/o/r/pull/9\n")
    )
    with pytest.raises(finish.FinishRefusal):
        _finish(tmp_path, monkeypatch, runner=runner)


def test_every_command_is_run_through_the_one_calling_convention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One place knows how a runner is called, including the probe inside `_commit`.

    A command run without ``capture_output`` would spill git and gh output into the
    operator's terminal and leave nothing to parse the pull request URL out of.
    """
    runner = _Runner(
        git_commit=_Proc(returncode=1, stderr="nothing to commit"),
        git_diff=_Proc(returncode=0),
    )
    _url, runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert runner.cmds("git", "diff")  # the probe ran, so it is covered below
    assert len(runner.kwargs) == len(runner.calls)
    for cmd, kwargs in zip(runner.calls, runner.kwargs, strict=True):
        assert kwargs["capture_output"] is True, cmd
        assert kwargs["text"] is True, cmd
        assert kwargs["cwd"] == str(tmp_path), cmd


def test_gh_exiting_zero_without_a_url_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returning "" would make an un-created pull request read as a created one."""
    with pytest.raises(finish.FinishRefusal):
        _finish(tmp_path, monkeypatch, runner=_Runner(gh=_Proc(stdout="\n")))


def test_the_commit_message_says_what_the_verdict_covers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subject carries a verdict, so the body has to bound it.

    "VERIFY PASS" over a commit means the generated tests passed against captured
    fixtures. It does not mean the adapter ingests the source, and a commit message
    read six months later is exactly where that gets misread.
    """
    _url, runner, _draft = _finish(
        tmp_path,
        monkeypatch,
        brief={"adapter_name": "cold_case_ok_osbi", "session_id": "20260831T140211Z-a3f9"},
    )
    (commit,) = runner.cmds("git", "commit")
    message = commit[commit.index("-m") + 1]
    assert "20260831T140211Z-a3f9" in message
    assert "nothing here has run against the live source" in message


def test_a_runner_that_answers_in_bytes_is_still_understood(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An injected runner need not have been given ``text=True`` by its author."""

    class _Bytes:
        returncode = 0
        stdout = b"https://github.com/o/r/pull/9\n"
        stderr = b""

    runner = _Runner(gh=_Bytes())  # type: ignore[arg-type]
    url, _runner, _draft = _finish(tmp_path, monkeypatch, runner=runner)
    assert url == "https://github.com/o/r/pull/9"


# --- the registry transition ---


def _registry_with(tmp_path: Path, status: Status, notes: str | None = None) -> Path:
    candidate = Candidate(
        id="ok__osbi",
        level=Level.STATE,
        state="OK",
        index_url="https://osbi.ok.gov/cold-cases",
        channel=Channel.WEB,
        status=status,
        notes=notes,
    )
    registry = scout_registry.Registry({}, [])
    registry.upsert(candidate)
    path = tmp_path / "registry.yaml"
    registry.save(path)
    return path


def _reload(path: Path) -> Candidate:
    candidate = scout_registry.Registry.load(path).get("ok__osbi")
    assert candidate is not None
    return candidate


def test_an_accepted_candidate_moves_to_needs_review_with_the_pr_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transition ``upsert`` cannot make.

    ``Registry.upsert`` enforces a no-regression rule over a lifecycle order in which
    ``accepted`` outranks ``needs_review``, so routing this through it would silently
    restore ``accepted`` and the write-back would be a no-op nobody noticed.
    """
    registry_path = _registry_with(tmp_path, Status.ACCEPTED)
    _url, _runner, _draft = _finish(
        tmp_path,
        monkeypatch,
        brief={"adapter_name": "cold_case_ok_osbi", "candidate_id": "ok__osbi"},
        registry_path=registry_path,
    )
    candidate = _reload(registry_path)
    assert candidate.status is Status.NEEDS_REVIEW
    assert candidate.notes is not None
    assert "https://github.com/o/r/pull/9" in candidate.notes
    assert "verify PASS" in candidate.notes


def test_an_ingested_candidate_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ingested`` is a human's statement about production; a re-draft does not retract it."""
    registry_path = _registry_with(tmp_path, Status.INGESTED)
    _url, _runner, draft_dir = _finish(
        tmp_path,
        monkeypatch,
        brief={"adapter_name": "cold_case_ok_osbi", "candidate_id": "ok__osbi"},
        registry_path=registry_path,
    )
    assert _reload(registry_path).status is Status.INGESTED
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    # The status alone is also held by the not-accepted branch below it, whose
    # explanation ("only an accepted candidate moves") reads as if this candidate had
    # never been accepted. An ingested one is PAST accepted, so it gets its own line.
    assert record["registry"].endswith("at ingested, which only a human retracts")


def test_a_second_finish_replaces_its_own_note_rather_than_stacking_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path = _registry_with(
        tmp_path, Status.ACCEPTED, notes="operator: check the county column"
    )
    brief = {"adapter_name": "cold_case_ok_osbi", "candidate_id": "ok__osbi"}
    for _ in range(2):
        _finish(tmp_path, monkeypatch, brief=brief, registry_path=registry_path)
    notes = _reload(registry_path).notes or ""
    assert notes.count(finish.NOTE_PREFIX) == 1
    assert "operator: check the county column" in notes


def test_a_broken_registry_is_a_warning_and_never_loses_the_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local bookkeeping on a gitignored file must not be able to fail an opened PR."""
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text("candidates: [not, a, mapping]\n")
    url, _runner, draft_dir = _finish(
        tmp_path,
        monkeypatch,
        brief={"adapter_name": "cold_case_ok_osbi", "candidate_id": "ok__osbi"},
        registry_path=registry_path,
    )
    assert url == "https://github.com/o/r/pull/9"
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["registry"].startswith("failed:")


def test_a_missing_registry_is_recorded_rather_than_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _url, _runner, draft_dir = _finish(
        tmp_path,
        monkeypatch,
        brief={"adapter_name": "cold_case_ok_osbi", "candidate_id": "ok__osbi"},
    )
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["registry"].startswith("skipped: no registry")


def test_a_candidate_that_was_never_accepted_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only an accepted candidate moves. A rejected one is a decision, not a state to step on."""
    registry_path = _registry_with(tmp_path, Status.REJECTED)
    _url, _runner, draft_dir = _finish(
        tmp_path,
        monkeypatch,
        brief={"adapter_name": "cold_case_ok_osbi", "candidate_id": "ok__osbi"},
        registry_path=registry_path,
    )
    assert _reload(registry_path).status is Status.REJECTED
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert "only an accepted candidate" in record["registry"]


def test_a_brief_with_no_candidate_id_says_so_rather_than_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path = _registry_with(tmp_path, Status.ACCEPTED)
    _url, _runner, draft_dir = _finish(tmp_path, monkeypatch, registry_path=registry_path)
    assert _reload(registry_path).status is Status.ACCEPTED
    record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text())
    assert record["registry"] == "skipped: the brief carries no candidate_id"


@pytest.mark.parametrize(
    "field,value",
    [
        ("headRefName", "another-branch"),
        ("state", "CLOSED"),
        ("body", "<!-- casesignal-adapter:other -->"),
        ("url", "not-a-pr"),
    ],
)
def test_finish_never_adopts_an_unrelated_or_invalid_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    info = {
        "url": "https://github.com/o/r/pull/9",
        "state": "OPEN",
        "headRefName": "draft/cold-case-ok-osbi",
        "body": "<!-- casesignal-adapter:cold_case_ok_osbi -->",
    }
    info[field] = value
    runner = _Runner(gh_create=_Proc(returncode=1), gh_view=_Proc(stdout=json.dumps(info)))
    with pytest.raises(finish.FinishRefusal):
        _finish(tmp_path, monkeypatch, runner=runner)
    assert not runner.cmds("gh", "pr", "edit")
    assert lease.read(tmp_path / "draft") is not None


def test_body_includes_advisory_live_result_and_verification_scope() -> None:
    from dataclasses import replace

    rounds, report = _reports(verify.VerifyStatus.PASS)
    report = replace(report, live_probe=("live adapter prepare_input: green; 4 captured records",))
    body = finish.build_pr_body({"adapter_name": "a"}, rounds, report)
    assert "Live probe (advisory)" in body
    assert "prepare_input: green" in body
    assert "Database persistence and production ingestion still require review" in body
