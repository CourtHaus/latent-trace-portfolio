"""The seam through which the code-writing agent is invoked.

These tests never touch the real ``claude`` binary: every one of them either
monkeypatches ``subprocess.run`` or exercises the in-process fake. The module is
security-relevant, so the assertions are mostly about what the built command
*refuses* to carry rather than what it carries.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import client as cl


def _completed(cmd: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def _ok_payload() -> str:
    return json.dumps({"result": "done", "is_error": False})


def _capturing(monkeypatch: pytest.MonkeyPatch, **completed: Any) -> dict[str, Any]:
    """Patch ``subprocess.run`` to record its arguments and return a canned process."""
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _completed(
            cmd,
            returncode=completed.get("returncode", 0),
            stdout=completed.get("stdout", _ok_payload()),
            stderr=completed.get("stderr", ""),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def _run(client: cl.DrafterClient, cwd: Path, **over: Any) -> cl.DrafterResult:
    prompt = over.pop("prompt", "do the thing")
    kwargs: dict[str, Any] = {
        "allowed_tools": cl.ALLOWED_TOOLS,
        "model": cl.DEFAULT_MODEL,
        "cwd": cwd,
        "timeout_s": 60,
    }
    kwargs.update(over)
    return client.run(prompt, **kwargs)


# --------------------------------------------------------------------------
# The tool allowlist itself
# --------------------------------------------------------------------------


def test_allowed_tools_excludes_bash() -> None:
    # Load-bearing, not cosmetic: without Bash the agent cannot run the tests,
    # reach the network, or touch git, which is what lets the loop's "green"
    # claim come from an exit code we observed rather than from the model.
    assert "Bash" not in cl.ALLOWED_TOOLS
    assert set(cl.ALLOWED_TOOLS) == {"Read", "Glob", "Grep", "Write", "Edit"}


def test_denied_tools_names_bash() -> None:
    assert "Bash" in cl.DENIED_TOOLS
    # Nothing may appear on both lists; a deny wins in Claude Code, so an overlap
    # would quietly disable a tool the drafter is supposed to have.
    assert set(cl.DENIED_TOOLS).isdisjoint(cl.ALLOWED_TOOLS)


def test_default_model_is_opus() -> None:
    assert cl.DEFAULT_MODEL == "opus"


# --------------------------------------------------------------------------
# The command the subprocess client builds
# --------------------------------------------------------------------------


def test_subprocess_client_builds_the_expected_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    result = cl.SubprocessDrafterClient().run(
        "do the thing",
        allowed_tools=cl.ALLOWED_TOOLS,
        model="opus",
        cwd=tmp_path,
        timeout_s=60,
    )

    cmd = seen["cmd"]
    assert cmd[0] == "claude"
    assert "-p" in cmd and "--output-format" in cmd and "json" in cmd
    assert "--model" in cmd and "opus" in cmd
    assert "--allowedTools" in cmd
    assert seen["kwargs"]["cwd"] == tmp_path
    assert result.ok is True


def test_the_prompt_is_the_last_argument_behind_an_end_of_options_separator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # -p is a boolean flag and the prompt is a positional. "--" ends option
    # parsing, so the prompt is the one argument the CLI cannot mistake for a flag.
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path, prompt="write the parser")
    cmd = seen["cmd"]
    assert cmd[-2:] == ["--", "write the parser"]


def test_a_prompt_beginning_with_a_dash_is_still_the_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Task 13 assembles prompts programmatically. Without the separator this one
    # is parsed as an unknown option and the round fails opaquely.
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path, prompt="--output-format is prose here")
    cmd = seen["cmd"]
    assert cmd.index("--") == len(cmd) - 2
    assert cmd[-1] == "--output-format is prose here"


def test_the_separator_sits_after_every_variadic_option(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    cmd = seen["cmd"]
    for flag in ("--add-dir", "--tools", "--allowedTools", "--disallowedTools"):
        assert cmd.index(flag) < cmd.index("--")


def test_no_variadic_option_is_left_dangling_at_the_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    cmd = seen["cmd"]
    for flag in ("--add-dir", "--allowedTools", "--disallowedTools"):
        index = cmd.index(flag)
        assert index < len(cmd) - 1, f"{flag} has no values"
        assert not cmd[index + 1].startswith("-"), f"{flag} consumed the next flag"


def test_bash_appears_only_after_the_deny_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Anywhere else in the command line, "Bash" would be a grant.
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    cmd = seen["cmd"]
    deny_at = cmd.index("--disallowedTools")
    assert [i for i, arg in enumerate(cmd) if "Bash" in arg] == [deny_at + 1]


def test_the_builtin_tool_set_is_pinned_to_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # --tools fixes which built-in tools exist at all, which is a stronger claim
    # than --allowedTools' permission grant: a tool that is not in the set cannot
    # be approved by any settings file.
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read,Glob,Grep,Write,Edit"


def test_the_builtin_tool_set_follows_a_narrower_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path, allowed_tools=("Read", "Grep"))
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep"
    assert cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")] == [
        "Read",
        "Grep",
    ]


def test_command_denies_bash_explicitly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An allowlist alone is not enough: the operator's own settings files can add
    # Bash permissions, and a deny rule outranks any allow rule wherever it came
    # from. This is the belt to --restricted's braces.
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--disallowedTools") + 1 : cmd.index("--")] == list(cl.DENIED_TOOLS)


def test_command_runs_restricted_and_ignores_ambient_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # --restricted drops the code-running tools from the built-in set and makes
    # the CLI ignore user, project and local settings files; --strict-mcp-config
    # drops ambient MCP servers, which would otherwise contribute tools this
    # module never reviewed.
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    assert "--restricted" in seen["cmd"]
    assert "--strict-mcp-config" in seen["cmd"]


def test_permission_mode_accepts_edits_without_bypassing_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in cmd
    assert "--allow-dangerously-skip-permissions" not in cmd
    assert "bypassPermissions" not in cmd


def test_add_dir_and_cwd_use_the_symlink_resolved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # If the worktree is reached through a symlink, --add-dir must name the real
    # directory. Otherwise the CLI's own confinement and apply-back's resolved
    # comparisons are reasoning about two different paths.
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), link)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--add-dir") + 1] == str(real.resolve())
    assert seen["kwargs"]["cwd"] == real.resolve()


def test_a_custom_binary_name_is_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(binary="/opt/claude"), tmp_path)
    assert seen["cmd"][0] == "/opt/claude"


def test_the_timeout_is_handed_to_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path, timeout_s=17)
    assert seen["kwargs"]["timeout"] == 17
    assert seen["kwargs"]["capture_output"] is True
    assert seen["kwargs"]["text"] is True


# --------------------------------------------------------------------------
# Refusals before anything is spawned
# --------------------------------------------------------------------------


def test_no_budget_flag_is_passed_when_none_is_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path)
    assert "--max-budget-usd" not in seen["cmd"]


def test_the_budget_ceiling_is_passed_when_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # With no --max-turns in this CLI, this is the only bound on a round that is
    # not the wall clock.
    seen = _capturing(monkeypatch)
    _run(cl.SubprocessDrafterClient(), tmp_path, max_budget_usd=2.5)
    cmd = seen["cmd"]
    assert cmd[cmd.index("--max-budget-usd") + 1] == "2.5"
    # It must land in the non-variadic run of the command, not after --allowedTools.
    assert cmd.index("--max-budget-usd") < cmd.index("--allowedTools")


def test_run_refuses_a_tool_outside_the_module_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The caller supplies allowed_tools, so the constant is only load-bearing if
    # the client refuses to widen past it. This is the test that fails the day
    # someone passes Bash in from the loop.
    spawned: list[list[str]] = []

    def record(cmd: list[str], **kwargs: Any) -> Any:
        spawned.append(cmd)
        return _completed(cmd)

    monkeypatch.setattr(subprocess, "run", record)
    with pytest.raises(cl.DrafterMisuse, match="Bash"):
        _run(cl.SubprocessDrafterClient(), tmp_path, allowed_tools=("Read", "Bash"))
    assert spawned == []


def test_run_refuses_an_empty_tool_list(tmp_path: Path) -> None:
    # "--allowedTools" with no values would consume the next flag as a value.
    with pytest.raises(cl.DrafterMisuse, match="no tools"):
        _run(cl.SubprocessDrafterClient(), tmp_path, allowed_tools=())


def test_run_refuses_a_haiku_model(tmp_path: Path) -> None:
    with pytest.raises(cl.DrafterMisuse, match="[Hh]aiku"):
        _run(cl.SubprocessDrafterClient(), tmp_path, model="claude-haiku-4-5")


def test_run_refuses_a_blank_model(tmp_path: Path) -> None:
    with pytest.raises(cl.DrafterMisuse, match="model"):
        _run(cl.SubprocessDrafterClient(), tmp_path, model="  ")


def test_run_refuses_a_nonpositive_timeout(tmp_path: Path) -> None:
    # The round budget lives in the caller's loop because this CLI has no
    # --max-turns, so the wall-clock timeout is the only thing that stops a
    # wedged round. A zero or negative budget is a bug, not a policy.
    with pytest.raises(cl.DrafterMisuse, match="timeout_s"):
        _run(cl.SubprocessDrafterClient(), tmp_path, timeout_s=0)


@pytest.mark.parametrize("budget", [0, -1.0, float("nan"), float("inf")])
def test_run_refuses_a_budget_that_is_not_positive_and_finite(
    tmp_path: Path, budget: float
) -> None:
    # inf is the load-bearing parameter: NaN, 0 and -1 are all refused by a plain
    # `> 0` check too, but `inf > 0` is True, so inf is the only one of the four
    # that actually exercises the isfinite half of the guard.
    with pytest.raises(cl.DrafterMisuse, match="max_budget_usd"):
        _run(cl.SubprocessDrafterClient(), tmp_path, max_budget_usd=budget)


def test_run_refuses_a_cwd_that_is_not_a_directory(tmp_path: Path) -> None:
    # Without this pre-check the FileNotFoundError subprocess raises for a
    # missing cwd is caught by the missing-binary handler and reported as
    # "claude not found on PATH" — the wrong diagnosis entirely.
    missing = tmp_path / "gone"
    with pytest.raises(cl.DrafterUnavailable) as exc:
        _run(cl.SubprocessDrafterClient(), missing)
    assert str(missing) in str(exc.value)
    assert "PATH" not in str(exc.value)


def test_run_refuses_a_cwd_that_is_a_file(tmp_path: Path) -> None:
    plain = tmp_path / "file.txt"
    plain.write_text("x")
    with pytest.raises(cl.DrafterUnavailable, match="directory"):
        _run(cl.SubprocessDrafterClient(), plain)


# --------------------------------------------------------------------------
# Failure modes of the spawned process
# --------------------------------------------------------------------------


def test_subprocess_client_raises_when_the_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(cmd: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(cl.DrafterUnavailable, match="claude"):
        _run(cl.SubprocessDrafterClient(), tmp_path)


def test_the_missing_binary_message_names_the_attempted_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(cmd: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(cl.DrafterUnavailable) as exc:
        _run(cl.SubprocessDrafterClient(binary="/opt/claude"), tmp_path)
    message = str(exc.value)
    assert "/opt/claude" in message
    assert "-p" in message
    # The prompt can be thousands of tokens of source; it must not be echoed.
    assert "do the thing" not in message


def test_a_binary_that_cannot_be_executed_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(cmd: list[str], **kwargs: Any) -> Any:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(cl.DrafterUnavailable, match="claude"):
        _run(cl.SubprocessDrafterClient(), tmp_path)


def test_subprocess_client_reports_failure_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _capturing(monkeypatch, returncode=1, stdout="", stderr="nope")
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is False
    assert "nope" in result.text


def test_a_nonzero_exit_still_keeps_a_json_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = json.dumps({"result": "hit the wall", "is_error": True, "subtype": "error"})
    _capturing(monkeypatch, returncode=1, stdout=payload, stderr="")
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is False
    assert result.raw["subtype"] == "error"
    # Equality, not containment: stdout is the JSON blob and happens to contain
    # this substring, so `in` would pass even if the payload were never consulted.
    assert result.text == "hit the wall"


def test_a_nonzero_exit_with_a_healthy_payload_still_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The exit code is authoritative. Without this case the return-code branch is
    # never the only thing separating pass from fail: the two other non-zero-exit
    # tests are also caught by the empty-stdout and is_error branches, so deleting
    # the return-code check entirely leaves them red for the wrong reason. Found by
    # pairing a mutant against the branch rather than the feature.
    _capturing(
        monkeypatch,
        returncode=1,
        stdout=json.dumps({"result": "looked fine", "is_error": False}),
        stderr="",
    )
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is False
    assert result.text == "looked fine"


def test_a_timeout_is_a_failed_round_naming_the_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(cmd: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", boom)
    result = _run(cl.SubprocessDrafterClient(), tmp_path, timeout_s=90)
    assert result.ok is False
    assert "90" in result.text
    assert "timed out" in result.text


def test_an_error_payload_fails_the_round_despite_a_zero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _capturing(monkeypatch, stdout=json.dumps({"result": "ran out", "is_error": True}))
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is False
    assert "ran out" in result.text


def test_malformed_stdout_fails_rather_than_passing_an_empty_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _capturing(monkeypatch, stdout="not json at all")
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is False
    assert "JSON" in result.text
    assert result.raw == {}


def test_a_json_payload_that_is_not_an_object_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _capturing(monkeypatch, stdout="[1, 2, 3]")
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is False
    assert result.raw == {}


def test_empty_stdout_fails_rather_than_passing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A zero exit with nothing on stdout is not a successful round: --output-format
    # json was requested, so silence means the CLI never produced a result.
    _capturing(monkeypatch, stdout="   \n")
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is False
    assert "no output" in result.text


def test_a_successful_result_carries_the_result_text_and_the_raw_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _capturing(monkeypatch, stdout=json.dumps({"result": "wrote the parser", "cost_usd": 0.4}))
    result = _run(cl.SubprocessDrafterClient(), tmp_path)
    assert result.ok is True
    assert result.text == "wrote the parser"
    assert result.raw["cost_usd"] == 0.4


# --------------------------------------------------------------------------
# The fake
# --------------------------------------------------------------------------


def test_fake_client_applies_scripted_writes_in_order(tmp_path: Path) -> None:
    def write(text: str) -> Callable[[Path], None]:
        def action(cwd: Path) -> None:
            (cwd / "scrape.py").write_text(text)

        return action

    fake = cl.FakeDrafterClient([write("# round 0\n"), write("# round 1\n")])
    fake.run("a", allowed_tools=cl.ALLOWED_TOOLS, model="opus", cwd=tmp_path, timeout_s=5)
    assert (tmp_path / "scrape.py").read_text() == "# round 0\n"
    fake.run("b", allowed_tools=cl.ALLOWED_TOOLS, model="opus", cwd=tmp_path, timeout_s=5)
    assert (tmp_path / "scrape.py").read_text() == "# round 1\n"
    assert fake.prompts == ["a", "b"]


def test_fake_client_records_every_call_argument(tmp_path: Path) -> None:
    fake = cl.FakeDrafterClient([lambda cwd: None])
    fake.run("a", allowed_tools=("Read",), model="opus", cwd=tmp_path, timeout_s=5)
    assert fake.calls[0]["model"] == "opus"
    assert fake.calls[0]["allowed_tools"] == ("Read",)
    assert fake.calls[0]["cwd"] == tmp_path
    assert fake.calls[0]["timeout_s"] == 5
    assert fake.calls[0]["max_budget_usd"] is None


def test_fake_client_enforces_the_same_refusals_as_the_real_one(tmp_path: Path) -> None:
    # A fake that accepts what the real client refuses hides the bug it exists to
    # catch: the loop's tests would pass with Bash in the tool list.
    fake = cl.FakeDrafterClient([lambda cwd: None])
    with pytest.raises(cl.DrafterMisuse, match="Bash"):
        fake.run("a", allowed_tools=("Bash",), model="opus", cwd=tmp_path, timeout_s=5)
    assert fake.prompts == []


def test_fake_client_reports_an_exhausted_script(tmp_path: Path) -> None:
    fake = cl.FakeDrafterClient([lambda cwd: None])
    fake.run("a", allowed_tools=cl.ALLOWED_TOOLS, model="opus", cwd=tmp_path, timeout_s=5)
    with pytest.raises(IndexError, match="exhausted"):
        fake.run("b", allowed_tools=cl.ALLOWED_TOOLS, model="opus", cwd=tmp_path, timeout_s=5)


def test_fake_client_returns_a_successful_result(tmp_path: Path) -> None:
    fake = cl.FakeDrafterClient([lambda cwd: None])
    result = fake.run("a", allowed_tools=cl.ALLOWED_TOOLS, model="opus", cwd=tmp_path, timeout_s=5)
    assert result.ok is True
    assert isinstance(result.raw, dict)


def test_the_package_spawn_guard_refuses_a_real_claude(tmp_path: Path) -> None:
    """The conftest guard, asserted directly rather than trusted.

    Every refusal test in this file depends on it: if a guard in
    _check_invocation regresses, run() falls through to subprocess.run, and this
    is what turns that into a red test instead of a billed agent session.
    """
    # Matched on the message rather than imported by name: the guard subclasses
    # AssertionError precisely so a spawn reads as a failed test, not an error.
    with pytest.raises(AssertionError, match="tried to execute 'claude' for real"):
        subprocess.run(["claude", "--version"], capture_output=True)


@pytest.mark.parametrize(
    ("name", "spawn"),
    [
        ("subprocess.run", lambda: subprocess.run(["claude", "--version"])),
        ("subprocess.Popen", lambda: subprocess.Popen(["claude", "--version"])),
        ("subprocess.call", lambda: subprocess.call(["claude", "--version"])),
        ("subprocess.check_call", lambda: subprocess.check_call(["claude", "--version"])),
        ("os.system", lambda: os.system("claude --version")),
        ("os.posix_spawn", lambda: os.posix_spawn("claude", ["claude"], {})),
    ],
)
def test_every_spawn_entry_point_is_denied_not_just_subprocess_run(
    name: str, spawn: Callable[[], object]
) -> None:
    """The conftest calls itself a structural deny-by-default; this is what makes it one.

    It used to patch `subprocess.run` alone, so `Popen`, `call`, `check_call`,
    `os.system` and `os.posix_spawn` walked past it. Nothing used them -- the guard held
    as a consequence of every spawn site happening to be written one way, which is the
    exact shape the conftest's own docstring argues against. A future site written with
    any of these would have spawned `claude` silently and billably.
    """
    with pytest.raises(AssertionError, match="tried to execute 'claude' for real"):
        spawn()


def test_the_spawn_guard_still_lets_the_two_permitted_programs_through() -> None:
    """Deny-by-default is only useful while the exceptions still work."""
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0


def test_both_implementations_satisfy_the_protocol(tmp_path: Path) -> None:
    clients: list[cl.DrafterClient] = [cl.SubprocessDrafterClient(), cl.FakeDrafterClient([])]
    assert len(clients) == 2
