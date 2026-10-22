"""Regression coverage for the SP2 audit: real Git and grading, fake paid agents."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from casesignal.drafter import cli, finish, lease, verify
from casesignal.drafter.client import FakeDrafterClient
from tests.integration import test_adapter_drafter_e2e as e2e

drafted = e2e.drafted


def _finish_args(draft: dict[str, Any]) -> Any:
    return cli.build_parser().parse_args(["finish", draft["adapter"]])


def _local_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    if cmd[0] == "gh":
        return subprocess.CompletedProcess(cmd, 0, "https://github.com/example/audit/pull/1\n", "")
    assert cmd[0] == "git"
    return subprocess.run(
        ["git", "-c", "user.name=Audit", "-c", "user.email=audit@localhost", *cmd[1:]],
        **kwargs,
    )


def test_finish_refuses_branch_drift(
    drafted: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    e2e._git(drafted["repo"], "checkout", "-b", "unrelated-feature")
    monkeypatch.setattr(cli, "_runner", lambda: _local_runner)
    with pytest.raises(finish.PreflightFailed, match="claimed destination"):
        cli._finish(
            _finish_args(drafted), drafted["repo"], drafted["draft_dir"].parent, drafted["adapter"]
        )
    assert drafted["worktree"].exists()
    assert lease.read(drafted["draft_dir"]) is not None


def test_failed_push_can_resume_without_redrafting(
    drafted: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    e2e._git(drafted["repo"], "remote", "add", "origin", str(remote))
    fail = True

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "push"] and fail:
            return subprocess.CompletedProcess(cmd, 1, "", "simulated push failure")
        return _local_runner(cmd, **kwargs)

    monkeypatch.setattr(cli, "_runner", lambda: runner)
    args = _finish_args(drafted)
    with pytest.raises(finish.CommandFailed):
        cli._finish(args, drafted["repo"], drafted["draft_dir"].parent, drafted["adapter"])
    assert drafted["worktree"].exists()
    assert lease.read(drafted["draft_dir"]) is not None
    fail = False
    cli._finish(args, drafted["repo"], drafted["draft_dir"].parent, drafted["adapter"])
    assert not drafted["worktree"].exists()
    assert lease.read(drafted["draft_dir"]) is None
    refs = subprocess.run(
        ["git", "--git-dir", str(remote), "for-each-ref", "--format=%(refname)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert refs.stdout.strip() == "refs/heads/draft/e2e"
    guard = subprocess.run(
        ["git", "--git-dir", str(remote), "show", "draft/e2e:tests/conftest.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "enforce_test_database" in guard.stdout
    assert len(drafted["agent"].calls) == 2


def test_reader_cannot_replace_captured_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = e2e._reader_round

    def changing_reader(cwd: Path) -> None:
        original(cwd)
        fixture = cwd / "fixtures/listing_1.html"
        fixture.write_text(fixture.read_text().replace("ALICE ANDERSON", "ALICIA ANDERSON"))

    monkeypatch.setattr(e2e, "_reader_round", changing_reader)
    result = cast(Any, e2e.drafted).__wrapped__(tmp_path, monkeypatch)
    assert result["code"] == 1
    assert len(result["agent"].calls) == 1
    manifest = json.loads((result["draft_dir"] / "manifest.json").read_text())
    raw = (result["draft_dir"] / "fixtures/listing_1.html").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["fixtures"][0]["sha256"]


@pytest.mark.parametrize("broken", ["required_todo", "stub_transform", "stub_mapping"])
def test_unfinished_transform_never_passes_the_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    broken: str,
) -> None:
    original = e2e._parser_round

    def factory(adapter_name: str) -> Any:
        write = original(adapter_name)

        def incomplete(cwd: Path) -> None:
            write(cwd)
            path = cwd / "src/casesignal/etl/adapters" / adapter_name / "transform.py"
            suffix = "\n# TODO(incident_date): unfinished\n"
            if broken == "stub_transform":
                suffix = "\ndef transform(context):\n    raise NotImplementedError\n"
            if broken == "stub_mapping":
                suffix = "\ndef to_case(record):\n    return {}\n"
            path.write_text(path.read_text() + suffix)

        return incomplete

    real_client = FakeDrafterClient
    monkeypatch.setattr(
        e2e,
        "FakeDrafterClient",
        lambda scripted: real_client([*scripted, scripted[-1], scripted[-1]]),
    )
    monkeypatch.setattr(e2e, "_parser_round", factory)
    result = cast(Any, e2e.drafted).__wrapped__(tmp_path, monkeypatch)
    assert result["code"] == 1
    args = cli.build_parser().parse_args(["verify", result["adapter"]])
    report = cli._verify(args, result["repo"], result["draft_dir"].parent, result["adapter"])
    assert report.status is verify.VerifyStatus.FAIL


def test_grading_cannot_read_or_write_host_files(tmp_path: Path) -> None:
    child = tmp_path / "grading"
    child.mkdir()
    secret = tmp_path / "host-canary.txt"
    secret.write_text("test sentinel")
    (child / "test_generated.py").write_text(
        "import pytest\nfrom pathlib import Path\n"
        f"def test_restrictions():\n    p = Path({str(secret)!r})\n"
        "    with pytest.raises(PermissionError):\n        p.read_text()\n"
        "    with pytest.raises(PermissionError):\n        p.write_text('changed')\n"
        "    import socket, subprocess\n"
        "    with pytest.raises(PermissionError):\n        socket.socket()\n"
        "    with pytest.raises(PermissionError):\n        subprocess.run(['/bin/true'])\n"
    )
    result = verify.run_pytest([Path("test_generated.py")], child)
    assert result.passed, result.raw
    assert secret.read_text() == "test sentinel"


@pytest.mark.parametrize(
    "body", ["import os; os._exit(0)", "import pytest; pytest.skip('all', allow_module_level=True)"]
)
def test_aborted_or_skipped_collection_is_not_a_pass(tmp_path: Path, body: str) -> None:
    (tmp_path / "test_generated.py").write_text(
        body + "\ndef test_never_runs():\n    assert False\n"
    )
    result = verify.run_pytest([Path("test_generated.py")], tmp_path)
    assert not result.passed


@pytest.mark.parametrize("max_requests,expected", [(5, "prepare_input: green"), (0, "incomplete")])
def test_live_probe_runs_actual_adapter_with_a_request_budget(
    drafted: dict[str, Any], monkeypatch: pytest.MonkeyPatch, max_requests: int, expected: str
) -> None:
    from casesignal.drafter import runtime

    outputs = []
    run_pytest = verify.run_pytest

    def grading(*args: Any, **kwargs: Any) -> verify.TestOutcome:
        result = run_pytest(*args, **kwargs)
        outputs.append(result.raw)
        return result

    monkeypatch.setattr(verify, "run_pytest", grading)
    client = e2e._FakeHttpClient()
    monkeypatch.setattr(runtime, "make_client", lambda spec: client)
    brief = json.loads((drafted["draft_dir"] / "brief.json").read_text())
    lines = cli._live_check(drafted["draft_dir"], brief, max_requests)
    assert expected in " ".join(lines), "\n".join(outputs)
    assert len(client.requested) == (1 if max_requests else 0)
    assert json.loads((drafted["draft_dir"] / "live.json").read_text())["lines"] == lines


def test_live_advisory_is_invalidated_when_adapter_changes(
    drafted: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from casesignal.drafter import live

    monkeypatch.setattr(live, "probe", lambda *args: ["live adapter prepare_input: green"])
    brief = json.loads((drafted["draft_dir"] / "brief.json").read_text())
    lines = cli._live_check(drafted["draft_dir"], brief, 5)
    assert cli._saved_live_check(drafted["draft_dir"], brief) == lines
    adapter = (
        drafted["worktree"] / "src/casesignal/etl/adapters" / drafted["adapter"] / "adapter.py"
    )
    adapter.write_text(adapter.read_text() + "\n# changed after probe\n")
    assert cli._saved_live_check(drafted["draft_dir"], brief) == []


def test_draft_resumes_its_recorded_workspace(
    drafted: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeDrafterClient([e2e._parser_round(drafted["adapter"])])
    monkeypatch.setattr(cli, "_drafter_client", lambda: client)
    args = cli.build_parser().parse_args(["draft", drafted["adapter"]])
    report = cli._draft(args, drafted["repo"], drafted["draft_dir"].parent)
    assert report.passed
    assert client.calls[0]["cwd"] == drafted["worktree"]
