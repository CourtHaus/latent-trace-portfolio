"""Tests for the parser loop, and for the barrier it exists to hold.

The security property is asserted directly rather than left as a consequence of
the implementation being right: several tests here fail if an expected value can
reach a prompt by ANY route -- through the failure feedback, through the brief's
own field-example block, or through the expectation module being readable in the
worktree while the agent runs.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import loop, verify, workspace
from casesignal.drafter.client import ALLOWED_TOOLS, FakeDrafterClient
from casesignal.drafter.reader import ExpectedRecord

ADAPTER = "cold_case_zz_test"
PACKAGE = f"{loop.ADAPTER_PACKAGE_ROOT}/{ADAPTER}"
INVARIANTS = f"tests/unit/etl/adapters/test_{ADAPTER}_invariants.py"


# --- fixtures ---


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _worktree(root: Path) -> workspace.Workspace:
    """A real git checkout standing in for the draft worktree.

    Real git, not a fake: ``changed_paths`` is what the loop's empty-round and
    stray-write gates are built on, and a fake status would test my model of git
    rather than the gate.
    """
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "core.excludesFile", "/dev/null")
    _git(root, "config", "commit.gpgsign", "false")
    package = root / PACKAGE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    invariants = root / INVARIANTS
    invariants.parent.mkdir(parents=True)
    invariants.write_text("def test_seed() -> None:\n    assert True\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return workspace.Workspace(branch="b", path=root, repo_root=root)


def _expectation_module(tmp_path: Path) -> Path:
    path = tmp_path / "expectations_src.py"
    path.write_text("def test_placeholder() -> None:\n    assert True\n")
    return path


def _brief(**extra: Any) -> dict[str, Any]:
    brief: dict[str, Any] = {
        "adapter_name": ADAPTER,
        "shape": "html",
        "index_url": "https://example.gov/cold-cases",
        "floors": {"case_name": 1.0, "incident_date": 0.9},
        "locators": {
            "case_name": {"kind": "css", "value": "h3 a", "page": "list"},
            "incident_date": {"kind": "css", "value": "time", "page": "list"},
        },
        "listing_paths": ["listing_1.html"],
        "detail_paths": [],
        # The classifier's own sample values. Rendering these would walk a golden
        # value into the prompt through a key nobody was thinking about.
        "fields": {
            "victim_name": {"present": True, "example": "Ann Example", "coverage": 1.0},
            "incident_date": {"present": True, "example": "1998-04-02", "coverage": 0.9},
        },
    }
    brief.update(extra)
    return brief


def _writes(name: str, body: str = "x") -> Any:
    def action(cwd: Path) -> None:
        target = cwd / PACKAGE / name
        target.write_text(f"# {body}\n")

    return action


def _outcome(**kw: Any) -> Any:
    def run_pytest(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        return verify.TestOutcome(**kw)

    return run_pytest


GOLDEN = [
    ExpectedRecord(
        "listing_1.html#0",
        {"victim_name": "Ann Example", "incident_date": "1998-04-02", "case_number": "98-1234"},
    )
]


# --- redaction ---


def test_redact_strips_expected_values_but_keeps_record_and_field() -> None:
    expectations = [ExpectedRecord("listing_1.html#0", {"incident_date": "1998-04-02"})]
    failures = [
        "FAILED test_expectations.py::test_golden_listing_1_html_0 - "
        "AssertionError: listing_1.html#0 incident_date: parsed '1998-02-04', "
        "expected '1998-04-02'"
    ]
    redacted = loop.redact(failures, expectations)
    assert "1998-04-02" not in redacted[0]
    assert "1998-02-04" not in redacted[0]
    assert "listing_1_html_0" in redacted[0]
    assert "incident_date" in redacted[0]
    assert "mismatch" in redacted[0]


def test_redact_recovers_the_field_name_from_the_reader_vocabulary() -> None:
    """The reader writes ``victim_name``; the generated test says ``case_name``."""
    expectations = [ExpectedRecord("listing_1.html#0", {"victim_name": "Ann Example"})]
    redacted = loop.redact(
        ["FAILED t.py::test_golden_x - AssertionError: x case_name: parsed None, expected 'Ann'"],
        expectations,
    )
    assert "case_name" in redacted[0]
    assert "Ann" not in redacted[0]


def test_redact_never_copies_a_token_the_expectations_did_not_name() -> None:
    """Field identity is SELECTED from an allowlist, never contributed to by the message."""
    expectations = [ExpectedRecord("listing_1.html#0", {"incident_date": "1998-04-02"})]
    redacted = loop.redact(
        ["FAILED t.py::test_a - AssertionError: SuspiciousToken incident_date mismatch"],
        expectations,
    )
    assert "SuspiciousToken" not in redacted[0]
    assert "incident_date" in redacted[0]


def test_redact_keeps_the_exception_class_for_a_non_assertion_failure() -> None:
    redacted = loop.redact(
        ["ERROR t.py::test_a - ImportError: cannot import name 'parse_records' from scrape"],
        GOLDEN,
    )
    assert redacted == ["ERROR t.py::test_a - ImportError"]


@pytest.mark.parametrize(
    "detail",
    [
        "AssertionError: assert '1998-02-04' == '1998-04-02'",
        "AssertionError: assert {'incident_date': None} == {'incident_date': '1998-04-02'}",
        "AssertionError: assert\n  - 1998-04-02\n  + None",
        "AssertionError: <Record incident_date=1998-04-02>",
        "ValueError: 98-1234 is not a date",
        "AssertionError: expected Ann Example",
    ],
)
def test_redact_leaks_no_value_whatever_shape_the_assertion_took(detail: str) -> None:
    """Reconstruction, not substitution: an unanticipated formatting cannot leak."""
    redacted = loop.redact([f"FAILED t.py::test_golden_0 - {detail}"], GOLDEN)
    for value in ("1998-04-02", "Ann Example", "98-1234"):
        assert value not in redacted[0]


def test_redact_drops_assertion_text_the_value_scan_could_not_know_about() -> None:
    """The reconstruction, pinned on its own rather than behind the value scan.

    The scan only knows the sampled records. An invariant test's message quotes
    whatever record actually failed, and most records were never sampled -- so a
    duplicate id, a stray narrative fragment, a parsed date from record 200 all
    pass the scan untouched. Only rebuilding the line from the node id keeps them
    out, and this is the case that tells the two mechanisms apart.
    """
    redacted = loop.redact(
        [
            "FAILED t.py::test_source_case_ids_are_unique - AssertionError: "
            "duplicate id 'OSBI-77-0142' across 3 records"
        ],
        GOLDEN,
    )
    assert redacted == ["FAILED t.py::test_source_case_ids_are_unique - mismatch"]


def test_redact_downgrades_a_test_name_that_carries_an_expected_value() -> None:
    """Not a parameter, so _PARAM cannot help: the scan downgrades to the file name."""
    redacted = loop.redact(
        ["FAILED t.py::test_golden_98-1234 - AssertionError: boom"],
        GOLDEN,
    )
    assert "98-1234" not in redacted[0]
    assert redacted[0].startswith("FAILED t.py - mismatch")
    assert "node name withheld" in redacted[0]


def test_redact_withholds_the_whole_line_when_even_the_file_name_carries_a_value() -> None:
    """The last fallback: nothing is left to name once the file name is contaminated."""
    redacted = loop.redact(["FAILED 1998-04-02_cases.py::test_a - AssertionError: x"], GOLDEN)
    assert "1998-04-02" not in redacted[0]
    assert redacted[0] == "FAILED <withheld: the failure identity carried an expected value>"


def test_redact_keeps_a_verify_diagnostic_that_names_no_value() -> None:
    line = "pytest exited 5 (no tests collected). The module imported and asserted nothing"
    assert loop.redact([line], GOLDEN) == [line]


def test_redact_withholds_a_diagnostic_that_carries_an_expected_value() -> None:
    redacted = loop.redact(["collection failed near Ann Example"], GOLDEN)
    assert "Ann Example" not in redacted[0]
    assert "withheld" in redacted[0]


def test_redact_ignores_values_too_short_to_be_leaked() -> None:
    """A two-character expectation would otherwise blank every node id containing it."""
    expectations = [ExpectedRecord("listing_1.html#0", {"victim_age": "17"})]
    redacted = loop.redact(
        ["FAILED t.py::test_golden_listing_17 - AssertionError: x"], expectations
    )
    assert "test_golden_listing_17" in redacted[0]


def test_redact_works_with_no_expectations_at_all() -> None:
    """The whitelist construction is the barrier; the value scan is only the second line."""
    redacted = loop.redact(["FAILED t.py::test_a - AssertionError: assert 'x' == 'Ann Example'"], [])
    assert redacted == ["FAILED t.py::test_a - mismatch"]


# --- the prompt ---


def test_prompt_never_contains_an_expected_value() -> None:
    failures = loop.redact(
        ["FAILED t.py::test_golden_0 - AssertionError: assert 'Anna Example' == 'Ann Example'"],
        GOLDEN,
    )
    prompt = loop.build_round_prompt(
        brief=_brief(), exemplar=loop.EXEMPLAR_STRUCTURED_HTML, failures=failures
    )
    assert "Ann Example" not in prompt


def test_prompt_never_renders_the_briefs_own_field_examples() -> None:
    """The leak route that is not the failure feedback: brief['fields'][..]['example']."""
    prompt = loop.build_round_prompt(
        brief=_brief(), exemplar=loop.EXEMPLAR_STRUCTURED_HTML, failures=[]
    )
    assert "Ann Example" not in prompt
    assert "1998-04-02" not in prompt


def test_the_brief_key_constant_names_no_key_that_carries_record_data() -> None:
    """A statement about the CONSTANT, not about the prompt.

    ``locators`` and ``floors`` are absent from this constant and are still
    rendered, deliberately, by ``_prompt_fields`` -- a locator is an address and a
    floor is a number. What must never appear here is a key whose value is
    per-record source data.
    """
    for key in ("fields", "coverage", "expectations", "record_list_basis"):
        assert key not in loop._PROMPT_BRIEF_KEYS
        assert key not in loop._PROMPT_FIXTURE_KEYS


def test_fixture_names_cannot_carry_anything_the_server_supplied() -> None:
    """The cross-module invariant that makes the fixture-path block safe to render.

    ``_fixture_lines`` renders listing_paths and detail_paths into the prompt. They
    are safe only because capture derives fixture names from a counter rather than
    from anything the source said, which lives in another module and is pinned
    here rather than assumed.
    """
    from casesignal.drafter.session import CaptureSession
    from casesignal.drafter.shapes import fixtures

    session = CaptureSession(session_id="s", shape="html", started_at="t", fixtures_root="fx")
    name = fixtures.fixture_name(
        session,
        "listing",
        1,
        "https://example.gov/OSBI-77-0142/Ann-Example?name=Ann+Example",
        suffix=".html",
    )
    assert name == "listing_1.html"
    for token in ("OSBI-77-0142", "Ann", "Example", "example.gov"):
        assert token not in name


def test_prompt_renders_the_locators_which_are_addresses_not_answers() -> None:
    prompt = loop.build_round_prompt(
        brief=_brief(), exemplar=loop.EXEMPLAR_STRUCTURED_HTML, failures=[]
    )
    assert "h3 a" in prompt
    assert "case_name" in prompt
    assert "floor 1.00" in prompt


def test_prompt_states_the_marked_todo_convention_in_the_form_verify_matches(
    tmp_path: Path,
) -> None:
    """Graded by verify.find_todos itself, so the prompt cannot drift from the matcher."""
    prompt = loop.build_round_prompt(brief=_brief(), exemplar=loop.EXEMPLAR_JSON, failures=[])
    as_module = tmp_path / "prompt_as_module.py"
    as_module.write_text(prompt, encoding="utf-8")
    illustrated = [todo.field for todo in verify.find_todos(as_module)]
    assert "county" in illustrated, "the prompt must show a marker verify.find_todos matches"
    assert "do not restate this convention" in prompt.lower()


def test_prompt_assigns_both_parser_modules() -> None:
    prompt = loop.build_round_prompt(brief=_brief(), exemplar=loop.EXEMPLAR_JSON, failures=[])
    assert "scrape.py" in prompt
    assert "transform.py" in prompt


def test_prompt_names_the_exemplar_package_and_the_memo() -> None:
    prompt = loop.build_round_prompt(
        brief=_brief(), exemplar=loop.EXEMPLAR_NARRATIVE_HTML, failures=[]
    )
    assert f"{loop.ADAPTER_PACKAGE_ROOT}/{loop.EXEMPLAR_NARRATIVE_HTML}/" in prompt
    assert f"docs/drafts/{ADAPTER}.md" in prompt


def test_prompt_says_the_first_round_has_run_nothing() -> None:
    prompt = loop.build_round_prompt(brief=_brief(), exemplar=loop.EXEMPLAR_JSON, failures=[])
    assert "first round" in prompt


# --- exemplar choice ---


@pytest.mark.parametrize("shape", ["socrata", "arcgis", "embedded_json"])
def test_a_json_capture_is_modelled_on_the_json_adapter(shape: str) -> None:
    assert loop.choose_exemplar(_brief(shape=shape)) == loop.EXEMPLAR_JSON


def test_json_path_locators_pick_the_json_adapter_whatever_the_shape_says() -> None:
    brief = _brief(locators={"a": {"kind": "json_path"}, "b": {"kind": "json_path"}})
    assert loop.choose_exemplar(brief) == loop.EXEMPLAR_JSON


def test_css_locators_pick_the_structured_html_adapter() -> None:
    assert loop.choose_exemplar(_brief()) == loop.EXEMPLAR_STRUCTURED_HTML


def test_label_locators_pick_the_narrative_adapter() -> None:
    brief = _brief(locators={"a": {"kind": "label"}, "b": {"kind": "label"}, "c": {"kind": "css"}})
    assert loop.choose_exemplar(brief) == loop.EXEMPLAR_NARRATIVE_HTML


def test_a_brief_naming_no_locators_falls_to_the_narrative_adapter() -> None:
    assert loop.choose_exemplar(_brief(locators={})) == loop.EXEMPLAR_NARRATIVE_HTML


def test_every_exemplar_is_a_real_in_tree_adapter() -> None:
    root = Path(__file__).resolve().parents[3]
    for exemplar in (
        loop.EXEMPLAR_STRUCTURED_HTML,
        loop.EXEMPLAR_NARRATIVE_HTML,
        loop.EXEMPLAR_JSON,
    ):
        assert (root / loop.ADAPTER_PACKAGE_ROOT / exemplar / "transform.py").is_file()


# --- the loop ---


def test_loop_stops_on_first_green_round(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))
    client = FakeDrafterClient([_writes("scrape.py")])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.passed is True
    assert len(report.rounds) == 1
    assert report.stopped_because == "green"


def test_loop_stops_early_on_a_repeated_failure_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(
        loop.verify, "run_pytest", _outcome(passed=False, failures=["FAILED t.py::x"], raw="")
    )
    client = FakeDrafterClient([_writes("scrape.py", str(n)) for n in range(3)])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        artifacts_dir=tmp_path / "rounds",
    )

    assert len(report.rounds) == 2
    assert report.stopped_because == "no-progress"
    assert report.passed is False


def test_loop_exhausts_the_round_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _worktree(tmp_path / "wt")
    seq = iter(["a", "b", "c"])

    def run_pytest(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        return verify.TestOutcome(passed=False, failures=[f"FAILED t.py::{next(seq)}"], raw="")

    monkeypatch.setattr(loop.verify, "run_pytest", run_pytest)
    client = FakeDrafterClient([_writes("scrape.py", str(n)) for n in range(3)])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        artifacts_dir=tmp_path / "rounds",
    )

    assert len(report.rounds) == 3
    assert report.stopped_because == "budget"


def test_loop_stops_on_a_round_the_wall_clock_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _worktree(tmp_path / "wt")
    seq = iter(["a", "b", "c"])

    def run_pytest(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        return verify.TestOutcome(passed=False, failures=[f"FAILED t.py::{next(seq)}"], raw="")

    monkeypatch.setattr(loop.verify, "run_pytest", run_pytest)

    clock = iter([0.0, 99.0, 100.0, 101.0, 200.0, 300.0])
    monkeypatch.setattr(loop, "_now", lambda: next(clock))

    class Slow(FakeDrafterClient):
        def run(self, prompt: str, **kw: Any) -> Any:
            result = super().run(prompt, **kw)
            return type(result)(ok=False, text="timed out", raw={})

    client = Slow([_writes("scrape.py", str(n)) for n in range(3)])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        timeout_s=90,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.stopped_because == "timeout"
    assert report.rounds[-1].timed_out is True


def test_a_failed_round_that_returned_promptly_is_not_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """timed_out is MEASURED, not read off the client's wording for its own failure."""
    ws = _worktree(tmp_path / "wt")
    seq = iter(["a", "b"])

    def run_pytest(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        return verify.TestOutcome(passed=False, failures=[f"FAILED t.py::{next(seq)}"], raw="")

    monkeypatch.setattr(loop.verify, "run_pytest", run_pytest)

    class Refuses(FakeDrafterClient):
        def run(self, prompt: str, **kw: Any) -> Any:
            result = super().run(prompt, **kw)
            return type(result)(ok=False, text="the model refused", raw={})

    report = loop.run_loop(
        ws=ws,
        client=Refuses([_writes("scrape.py", str(n)) for n in range(2)]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=2,
        artifacts_dir=tmp_path / "rounds",
    )

    assert [r.timed_out for r in report.rounds] == [False, False]
    assert report.stopped_because == "budget"


def test_a_round_that_changed_nothing_is_a_failed_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gitignored writes are invisible to changed_paths, so silence is not success."""
    ws = _worktree(tmp_path / "wt")
    ran: list[bool] = []

    def run_pytest(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        ran.append(True)
        return verify.TestOutcome(passed=True, failures=[], raw="")

    monkeypatch.setattr(loop.verify, "run_pytest", run_pytest)
    client = FakeDrafterClient([lambda cwd: None, lambda cwd: None])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=2,
        artifacts_dir=tmp_path / "rounds",
    )

    assert ran == []
    assert report.passed is False
    assert report.rounds[0].signature == "no-changes"
    assert report.stopped_because == "no-progress"


def test_a_round_that_wrote_outside_the_allowlist_ends_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    def stray(cwd: Path) -> None:
        (cwd / "src" / "casesignal" / "normalization.py").parent.mkdir(parents=True, exist_ok=True)
        (cwd / "src" / "casesignal" / "normalization.py").write_text("# owned\n")

    client = FakeDrafterClient([stray, _writes("scrape.py")])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.stopped_because == "wrote-outside-allowlist"
    assert len(report.rounds) == 1


def test_a_round_that_deleted_a_tracked_file_ends_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cumulative status: one deletion wedges every later apply_back, so retrying is waste."""
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    def delete(cwd: Path) -> None:
        (cwd / PACKAGE / "__init__.py").unlink()

    client = FakeDrafterClient([delete, _writes("scrape.py")])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.stopped_because == "deleted-in-workspace"
    assert len(report.rounds) == 1


def test_loop_refuses_a_worktree_already_dirty_outside_the_allowlist(tmp_path: Path) -> None:
    ws = _worktree(tmp_path / "wt")
    (ws.path / "unrelated.txt").write_text("someone else's work\n")

    with pytest.raises(loop.LoopRefusal, match="cumulative"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=tmp_path / "rounds",
        )


def test_a_scaffolded_worktree_is_not_too_dirty_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dirt inside the allowlist is the scaffold; refusing it would refuse every run."""
    ws = _worktree(tmp_path / "wt")
    (ws.path / PACKAGE / "adapter.py").write_text("# scaffolded\n")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    report = loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([_writes("scrape.py")]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        artifacts_dir=tmp_path / "rounds",
    )
    assert report.stopped_because == "green"


# --- the barrier ---


def test_expectation_module_is_absent_from_the_worktree_while_the_agent_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))
    observed: list[bool] = []

    def observe(cwd: Path) -> None:
        observed.append((cwd / loop.EXPECTATION_MODULE_NAME).exists())
        (cwd / PACKAGE / "scrape.py").write_text("# ok\n")

    loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([observe]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=1,
        artifacts_dir=tmp_path / "rounds",
    )

    assert observed == [False]
    assert not (ws.path / loop.EXPECTATION_MODULE_NAME).exists()


def test_the_injected_module_is_removed_even_when_the_test_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injection window is the weak point; the removal is in a finally."""
    ws = _worktree(tmp_path / "wt")

    def explode(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        raise RuntimeError("pytest blew up mid-run")

    monkeypatch.setattr(loop.verify, "run_pytest", explode)

    with pytest.raises(RuntimeError):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            rounds=1,
            artifacts_dir=tmp_path / "rounds",
        )

    assert not (ws.path / loop.EXPECTATION_MODULE_NAME).exists()


def test_no_prompt_in_any_round_carries_an_expected_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole barrier, end to end, with the failures quoting the answers."""
    ws = _worktree(tmp_path / "wt")
    shapes = iter(
        [
            [
                "FAILED test_expectations.py::test_golden_listing_1_html_0 - AssertionError: "
                "listing_1.html#0 case_name: parsed 'Anna Example', expected 'Ann Example'"
            ],
            [
                "FAILED test_expectations.py::test_golden_listing_1_html_0 - AssertionError: "
                "assert {'incident_date': None} == {'incident_date': '1998-04-02'}"
            ],
            [
                "ERROR test_expectations.py::test_golden_listing_1_html_0 - "
                "ValueError: 98-1234 is not a date"
            ],
        ]
    )

    def run_pytest(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        return verify.TestOutcome(passed=False, failures=next(shapes), raw="raw with Ann Example")

    monkeypatch.setattr(loop.verify, "run_pytest", run_pytest)
    client = FakeDrafterClient([_writes("scrape.py", str(n)) for n in range(3)])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        expectations=GOLDEN,
        artifacts_dir=tmp_path / "rounds",
    )

    assert len(report.rounds) == 3
    assert client.prompts
    for prompt in client.prompts:
        for value in ("Ann Example", "1998-04-02", "98-1234"):
            assert value not in prompt, f"{value!r} reached a prompt"
    # And the feedback still says which record and which field.
    assert "test_golden_listing_1_html_0" in client.prompts[1]
    assert "case_name" in client.prompts[1]


def test_loop_refuses_an_expectation_module_inside_the_worktree(tmp_path: Path) -> None:
    ws = _worktree(tmp_path / "wt")
    inside = ws.path / "expectations_src.py"
    inside.write_text("def test_x() -> None:\n    assert True\n")

    with pytest.raises(loop.BarrierViolation, match="inside the worktree"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=inside,
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=tmp_path / "rounds",
        )


def test_loop_refuses_an_artifacts_dir_inside_the_worktree(tmp_path: Path) -> None:
    """pytest.txt holds raw output, and raw output quotes the answers verbatim."""
    ws = _worktree(tmp_path / "wt")

    with pytest.raises(loop.BarrierViolation, match="raw pytest output"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=ws.path / "rounds",
        )


def test_loop_refuses_a_test_path_outside_the_worktree(tmp_path: Path) -> None:
    ws = _worktree(tmp_path / "wt")
    outside = tmp_path / "elsewhere.py"
    outside.write_text("def test_x() -> None:\n    assert True\n")

    with pytest.raises(loop.BarrierViolation, match="outside the worktree"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[outside],
            artifacts_dir=tmp_path / "rounds",
        )


def test_loop_refuses_a_caller_that_names_the_injected_module(tmp_path: Path) -> None:
    ws = _worktree(tmp_path / "wt")
    (ws.path / loop.EXPECTATION_MODULE_NAME).write_text("def test_x() -> None:\n    assert True\n")

    with pytest.raises(loop.BarrierViolation, match="run_loop injects"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(loop.EXPECTATION_MODULE_NAME)],
            artifacts_dir=tmp_path / "rounds",
        )


def test_loop_refuses_an_empty_test_path_list(tmp_path: Path) -> None:
    """An empty list falls back to pyproject's testpaths: the whole repo suite, per round."""
    ws = _worktree(tmp_path / "wt")

    with pytest.raises(verify.NoTestPaths):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[],
            artifacts_dir=tmp_path / "rounds",
        )


def test_loop_refuses_a_test_path_that_is_not_in_the_worktree(tmp_path: Path) -> None:
    ws = _worktree(tmp_path / "wt")

    with pytest.raises(loop.LoopRefusal, match="does not exist"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path("tests/unit/etl/adapters/test_never_scaffolded.py")],
            artifacts_dir=tmp_path / "rounds",
        )


def test_the_injection_really_runs_the_golden_module_and_then_removes_it(
    tmp_path: Path,
) -> None:
    """Real pytest, real copy, real unlink: the one window the barrier depends on."""
    ws = _worktree(tmp_path / "wt")
    expectation_module = tmp_path / "expectations_src.py"
    expectation_module.write_text(
        "from pathlib import Path\n\n\n"
        "def test_golden_listing_1_html_0() -> None:\n"
        "    assert Path('" + PACKAGE + "/scrape.py').read_text().strip() == '# parsed'\n"
    )

    report = loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([_writes("scrape.py", "parsed")]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=expectation_module,
        test_paths=[Path(INVARIANTS)],
        rounds=1,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.passed is True
    assert report.stopped_because == "green"
    assert "2 passed" in (tmp_path / "rounds" / "00" / "pytest.txt").read_text()
    assert not (ws.path / loop.EXPECTATION_MODULE_NAME).exists()


def test_the_injected_module_actually_grades_the_draft(tmp_path: Path) -> None:
    """The mirror of the test above: a wrong parser goes red through the same route."""
    ws = _worktree(tmp_path / "wt")
    expectation_module = tmp_path / "expectations_src.py"
    expectation_module.write_text(
        "from pathlib import Path\n\n\n"
        "def test_golden_listing_1_html_0() -> None:\n"
        "    assert Path('" + PACKAGE + "/scrape.py').read_text().strip() == '# parsed'\n"
    )

    report = loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([_writes("scrape.py", "wrong")]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=expectation_module,
        test_paths=[Path(INVARIANTS)],
        rounds=1,
        expectations=GOLDEN,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.passed is False
    assert "test_golden_listing_1_html_0" in report.rounds[0].signature


# --- invocation and artifacts ---


def test_the_loop_passes_a_spend_ceiling_and_the_parser_tool_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no --max-turns, so an unexercised opt-in would be no dollar bound at all."""
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))
    client = FakeDrafterClient([_writes("scrape.py")])

    loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=1,
        artifacts_dir=tmp_path / "rounds",
    )

    call = client.calls[0]
    assert call["max_budget_usd"] == loop.DEFAULT_PARSER_BUDGET_USD
    assert call["max_budget_usd"] is not None
    assert call["allowed_tools"] == tuple(ALLOWED_TOOLS)
    assert "haiku" not in call["model"]
    assert call["timeout_s"] == loop.DEFAULT_ROUND_TIMEOUT_S
    assert call["cwd"] == ws.path


def test_round_artifacts_are_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(
        loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw="1 passed")
    )
    artifacts = tmp_path / "rounds"

    loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([_writes("scrape.py")]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=1,
        artifacts_dir=artifacts,
    )

    assert (artifacts / "00" / "prompt.md").exists()
    assert (artifacts / "00" / "pytest.txt").read_text() == "1 passed"

    import json

    record = json.loads((artifacts / "00" / "result.json").read_text())
    assert record["passed"] is True
    assert record["verdict"] == "green"
    assert f"{PACKAGE}/scrape.py" in record["changed_paths"]


def test_result_json_records_the_marked_todos_from_both_parser_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    def writes_both(cwd: Path) -> None:
        (cwd / PACKAGE / "scrape.py").write_text("# TODO(county): no county on the listing\n")
        (cwd / PACKAGE / "transform.py").write_text("# TODO(victim_age): narrative only\n")

    loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([writes_both]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=1,
        artifacts_dir=tmp_path / "rounds",
    )

    import json

    record = json.loads((tmp_path / "rounds" / "00" / "result.json").read_text())
    assert sorted(todo["field"] for todo in record["todos"]) == ["county", "victim_age"]


def test_dry_run_assembles_the_prompt_and_spawns_nothing(tmp_path: Path) -> None:
    ws = _worktree(tmp_path / "wt")

    def explode(cwd: Path) -> None:
        raise AssertionError("the client must not be invoked during a dry run")

    report = loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([explode]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        artifacts_dir=tmp_path / "rounds",
        dry_run=True,
    )

    assert report.stopped_because == "dry-run"
    assert report.rounds == []
    assert "scrape.py" in (tmp_path / "rounds" / "00" / "prompt.md").read_text()


@pytest.mark.parametrize(("rounds", "timeout_s"), [(0, 900), (-1, 900), (3, 0), (3, -5)])
def test_loop_refuses_a_budget_that_bounds_nothing(
    tmp_path: Path, rounds: int, timeout_s: int
) -> None:
    ws = _worktree(tmp_path / "wt")

    with pytest.raises(loop.LoopRefusal):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            rounds=rounds,
            timeout_s=timeout_s,
            artifacts_dir=tmp_path / "rounds",
        )


def test_the_run_has_a_ceiling_of_its_own_and_not_only_a_per_round_one() -> None:
    """`--rounds` was an unbounded operator-typed integer with the budget per ROUND.

    `--rounds 30` for `--rounds 3` is thirty unattended agent sessions, and the wall
    clock -- the only other bound, since this CLI has no `--max-turns` -- scales with
    the count rather than against it.
    """
    with pytest.raises(loop.LoopRefusal, match="over the run ceiling"):
        loop.check_round_bounds(loop.MAX_ROUNDS + 1, loop.DEFAULT_PARSER_BUDGET_USD)


def test_the_run_ceiling_is_a_dollar_figure_as_well_as_a_count() -> None:
    """Ten rounds at a raised per-round budget is over the ceiling ten rounds is under."""
    over = loop.MAX_RUN_BUDGET_USD / loop.MAX_ROUNDS + 1
    with pytest.raises(loop.LoopRefusal, match="for one unattended run"):
        loop.check_round_bounds(loop.MAX_ROUNDS, over)


def test_the_default_run_is_comfortably_inside_both_ceilings() -> None:
    """A ceiling that refuses the shipped defaults is a ceiling nobody can use."""
    loop.check_round_bounds(loop.DEFAULT_ROUNDS, loop.DEFAULT_PARSER_BUDGET_USD)
    loop.check_round_bounds(loop.MAX_ROUNDS, loop.DEFAULT_PARSER_BUDGET_USD)
    loop.check_round_bounds(loop.DEFAULT_ROUNDS, None)


# --- helpers other tasks bind to ---


def test_parser_module_paths_names_both_modules(tmp_path: Path) -> None:
    paths = loop.parser_module_paths(tmp_path, ADAPTER)
    assert [p.name for p in paths] == ["scrape.py", "transform.py"]
    assert all(
        str(p).startswith(str(tmp_path / loop.ADAPTER_PACKAGE_ROOT / ADAPTER)) for p in paths
    )


def test_parser_todos_scans_both_modules(tmp_path: Path) -> None:
    package = tmp_path / PACKAGE
    package.mkdir(parents=True)
    (package / "scrape.py").write_text("# TODO(county): the listing prints none\n")
    (package / "transform.py").write_text("# TODO(case_name): unreachable\n")
    assert sorted(t.field for t in loop.parser_todos(tmp_path, ADAPTER)) == ["case_name", "county"]


def test_parser_todos_tolerates_a_module_not_yet_written(tmp_path: Path) -> None:
    package = tmp_path / PACKAGE
    package.mkdir(parents=True)
    (package / "scrape.py").write_text("# TODO(county): the listing prints none\n")
    assert [t.field for t in loop.parser_todos(tmp_path, ADAPTER)] == ["county"]


def test_default_allowed_paths_is_the_adapter_package_and_nothing_else() -> None:
    assert loop.default_allowed_paths(_brief()) == [PACKAGE]


def test_the_allowlist_excludes_the_generated_tests() -> None:
    """A pass that can edit the tests grading it is not being graded."""
    allowed = loop.default_allowed_paths(_brief())
    assert workspace.stray_writes([INVARIANTS], allowed) == [INVARIANTS]


def test_redact_strips_a_parametrised_node_id(tmp_path: Path) -> None:
    """The node id is free text in exactly one place, and it is not trusted there."""
    redacted = loop.redact(
        ["FAILED t.py::test_field[OSBI-77-0142] - AssertionError: boom"],
        GOLDEN,
    )
    assert redacted == ["FAILED t.py::test_field[...] - mismatch"]


def test_redact_strips_a_parameter_the_value_scan_could_not_know_about() -> None:
    """The M4 asymmetry, on the node id this time: the scan sees only sampled records."""
    redacted = loop.redact(
        ["FAILED t.py::test_field[UNSAMPLED-9931] - AssertionError: boom"],
        GOLDEN,
    )
    assert "UNSAMPLED-9931" not in redacted[0]


def test_no_parametrised_node_id_reaches_a_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _worktree(tmp_path / "wt")

    def run_pytest(paths: Any, cwd: Any, **_: Any) -> verify.TestOutcome:
        return verify.TestOutcome(
            passed=False,
            failures=["FAILED t.py::test_field[OSBI-77-0142] - AssertionError: x"],
            raw="",
        )

    monkeypatch.setattr(loop.verify, "run_pytest", run_pytest)
    client = FakeDrafterClient([_writes("scrape.py", str(n)) for n in range(2)])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=2,
        expectations=GOLDEN,
        artifacts_dir=tmp_path / "rounds",
    )

    assert "OSBI-77-0142" not in client.prompts[1]
    assert "OSBI-77-0142" not in report.rounds[0].signature


def test_a_round_that_planted_a_symlink_ends_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply_back refuses a symlink whatever happens next, so further rounds are waste."""
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    def plant(cwd: Path) -> None:
        (cwd / PACKAGE / "scrape.py").symlink_to(tmp_path / "elsewhere.py")

    client = FakeDrafterClient([plant, _writes("transform.py")])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=3,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.stopped_because == "unsupported-entry"
    assert len(report.rounds) == 1


def test_a_broken_symlink_is_attributed_to_the_symlink_and_not_to_a_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exists() follows links, so the symlink test has to come first."""
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    def plant(cwd: Path) -> None:
        (cwd / PACKAGE / "scrape.py").symlink_to(cwd / PACKAGE / "does_not_exist.py")

    report = loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([plant]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=1,
        artifacts_dir=tmp_path / "rounds",
    )

    assert report.stopped_because == "unsupported-entry"


def test_loop_refuses_a_worktree_carrying_this_adapters_golden_module(tmp_path: Path) -> None:
    """The re-draft case: a merged draft puts the answers in every later worktree."""
    ws = _worktree(tmp_path / "wt")
    committed = ws.path / "tests/unit/etl/adapters" / f"test_{ADAPTER}_expectations.py"
    committed.write_text('EXPECTATIONS = {"listing_1.html#0": {"case_name": "Ann Example"}}\n')
    _git(ws.path, "add", "-A")
    _git(ws.path, "commit", "-q", "-m", "a previous draft")

    with pytest.raises(loop.BarrierViolation, match="golden module"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=tmp_path / "rounds",
        )


def test_the_golden_module_check_sees_a_committed_file_the_dirty_guard_cannot(
    tmp_path: Path,
) -> None:
    """It is tracked and clean, so changed_paths reports nothing about it."""
    ws = _worktree(tmp_path / "wt")
    committed = ws.path / "tests/unit/etl/adapters" / f"test_{ADAPTER}_expectations.py"
    committed.write_text("EXPECTATIONS = {}\n")
    _git(ws.path, "add", "-A")
    _git(ws.path, "commit", "-q", "-m", "a previous draft")

    assert workspace.changed_paths(ws) == []
    with pytest.raises(loop.BarrierViolation):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=tmp_path / "rounds",
        )


def test_loop_refuses_a_stale_named_module_carrying_this_runs_values(tmp_path: Path) -> None:
    """The same module under an adapter name that has since changed."""
    ws = _worktree(tmp_path / "wt")
    stale = ws.path / "tests/unit/etl/adapters/test_cold_case_zz_old_name_expectations.py"
    stale.write_text('EXPECTATIONS = {"listing_1.html#0": {"case_name": "Ann Example"}}\n')
    # COMMITTED, which is the dangerous form: untracked, the dirty-worktree guard
    # would refuse the run first and this test would pass without the content
    # check ever running.
    _git(ws.path, "add", "-A")
    _git(ws.path, "commit", "-q", "-m", "a draft under the old adapter name")
    assert workspace.changed_paths(ws) == []

    with pytest.raises(loop.BarrierViolation, match="values this run transcribed"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            expectations=GOLDEN,
            artifacts_dir=tmp_path / "rounds",
        )


def test_a_sibling_adapters_golden_module_does_not_refuse_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blanket glob would refuse the second adapter this pipeline ever drafts."""
    ws = _worktree(tmp_path / "wt")
    sibling = ws.path / "tests/unit/etl/adapters/test_cold_case_other_expectations.py"
    sibling.write_text('EXPECTATIONS = {"listing_1.html#0": {"case_name": "Someone Else"}}\n')
    _git(ws.path, "add", "-A")
    _git(ws.path, "commit", "-q", "-m", "another adapter")
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    report = loop.run_loop(
        ws=ws,
        client=FakeDrafterClient([_writes("scrape.py")]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        expectations=GOLDEN,
        artifacts_dir=tmp_path / "rounds",
    )
    assert report.stopped_because == "green"


def test_the_in_tree_check_reads_its_values_off_the_module_being_injected(
    tmp_path: Path,
) -> None:
    """No `expectations` argument, and the stale-name check still fires."""
    ws = _worktree(tmp_path / "wt")
    stale = ws.path / "tests/unit/etl/adapters/test_cold_case_zz_old_name_expectations.py"
    stale.write_text('EXPECTATIONS = {"listing_1.html#0": {"case_name": "Ann Example"}}\n')
    _git(ws.path, "add", "-A")
    _git(ws.path, "commit", "-q", "-m", "a draft under the old adapter name")
    assert workspace.changed_paths(ws) == []

    module = tmp_path / "expectations_src.py"
    module.write_text(
        "EXPECTATIONS: dict[str, dict[str, str]] = {\n"
        '    "listing_1.html#0": {"case_name": "Ann Example"},\n'
        "}\n"
    )

    with pytest.raises(loop.BarrierViolation, match="values this run transcribed"):
        loop.run_loop(
            ws=ws,
            client=FakeDrafterClient([_writes("scrape.py")]),
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=module,
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=tmp_path / "rounds",
        )


def test_expectations_read_off_a_module_that_binds_nothing_are_empty(tmp_path: Path) -> None:
    module = tmp_path / "hand_written.py"
    module.write_text("def test_x() -> None:\n    assert True\n")
    assert loop._expectations_from_module(module) == []


def test_expectations_are_read_only_off_the_expectations_binding(tmp_path: Path) -> None:
    """A module-level dict is not automatically a set of golden values."""
    module = tmp_path / "other_binding.py"
    module.write_text(
        'FIXTURE_INDEX = {"listing_1.html#0": {"case_name": "Ann Example"}}\n'
        'EXPECTATIONS = {"listing_2.html#3": {"county": "Pulaski"}}\n'
    )
    records = loop._expectations_from_module(module)
    assert [r.record_key for r in records] == ["listing_2.html#3"]
    assert records[0].values == {"county": "Pulaski"}


def test_a_no_changes_round_persists_no_feedback_from_a_run_that_did_not_happen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The previous round's failures are not this round's, and no test ran here.

    Driven through ``changed_paths``, because a worktree's status is cumulative:
    once a round has written anything the set is never empty again, so a red round
    followed by a no-changes round cannot be staged with real writes alone.
    """
    ws = _worktree(tmp_path / "wt")
    monkeypatch.setattr(
        loop.verify, "run_pytest", _outcome(passed=False, failures=["FAILED t.py::a"], raw="")
    )
    seen: list[int] = []
    real = loop.workspace.changed_paths

    def changed_paths(w: Any) -> list[str]:
        seen.append(1)
        # Call 1 is the pre-flight dirty check, call 2 is round 0, call 3 is round 1.
        return [] if len(seen) > 2 else real(w)

    monkeypatch.setattr(loop.workspace, "changed_paths", changed_paths)
    client = FakeDrafterClient([_writes("scrape.py"), lambda cwd: None])

    report = loop.run_loop(
        ws=ws,
        client=client,
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        rounds=2,
        artifacts_dir=tmp_path / "rounds",
    )

    import json

    first = json.loads((tmp_path / "rounds" / "00" / "result.json").read_text())
    second = json.loads((tmp_path / "rounds" / "01" / "result.json").read_text())
    assert first["failures_redacted"] == ["FAILED t.py::a - mismatch"]
    assert second["signature"] == "no-changes"
    assert second["failures_redacted"] == []
    assert report.stopped_because == "budget"


def test_the_golden_literal_is_what_the_generator_actually_binds(tmp_path: Path) -> None:
    """The cross-module coupling the whole content check rests on, pinned end to end.

    ``_expectations_from_module`` looks for one name in a module another module
    generates. Rename that binding in ``templates.EXPECTATION_TESTS`` and this
    module silently returns [] -- which turns OFF both the stale-name content
    check and, under the default expectations=None, redact's value scan. Nothing
    else in the tree would go red. So the real generator is rendered here and read
    back through the real reader.
    """
    import ast

    from casesignal.drafter import scaffold

    rendered = scaffold.render_expectation_tests(
        [ExpectedRecord("listing_1.html#0", {"victim_name": "Ann Example"})], ADAPTER
    )
    targets = {
        name.id
        for node in ast.parse(rendered).body
        for name in (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else (node.targets if isinstance(node, ast.Assign) else [])
        )
        if isinstance(name, ast.Name)
    }
    assert loop._GOLDEN_LITERAL in targets

    module = tmp_path / "rendered_expectations.py"
    module.write_text(rendered, encoding="utf-8")
    records = loop._expectations_from_module(module)
    assert [r.record_key for r in records] == ["listing_1.html#0"]
    assert records[0].values == {"case_name": "Ann Example"}


def test_loop_refuses_a_committed_copy_under_the_injection_filename(tmp_path: Path) -> None:
    """The one filename the glob most obviously has to cover: the loop's own."""
    ws = _worktree(tmp_path / "wt")
    planted = ws.path / loop.EXPECTATION_MODULE_NAME
    planted.write_text('EXPECTATIONS = {"listing_1.html#0": {"case_name": "Ann Example"}}\n')
    _git(ws.path, "add", "-A")
    _git(ws.path, "commit", "-q", "-m", "committed under the injection name")
    assert workspace.changed_paths(ws) == []

    client = FakeDrafterClient([_writes("scrape.py")])
    with pytest.raises(loop.BarrierViolation, match="name this loop injects"):
        loop.run_loop(
            ws=ws,
            client=client,
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=tmp_path / "rounds",
        )
    assert client.prompts == [], "not one round may be bought before this is caught"


def test_loop_refuses_a_repository_whose_allowlist_prefix_is_reached_through_a_symlink(
    tmp_path: Path,
) -> None:
    """apply_back would refuse the finished draft; the whole budget would go first."""
    ws = _worktree(tmp_path / "wt")
    main = tmp_path / "main"
    (main / "src" / "casesignal" / "etl").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (main / "src" / "casesignal" / "etl" / "adapters").symlink_to(elsewhere)

    client = FakeDrafterClient([_writes("scrape.py")])
    with pytest.raises(loop.LoopRefusal, match="a symlink stands on the path"):
        loop.run_loop(
            ws=replace(ws, repo_root=main),
            client=client,
            brief=_brief(),
            exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
            expectation_module=_expectation_module(tmp_path),
            test_paths=[Path(INVARIANTS)],
            artifacts_dir=tmp_path / "rounds",
        )
    assert client.prompts == [], "the refusal must land before a round is bought"


def test_an_allowlist_prefix_that_does_not_exist_yet_is_not_a_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary first draft: nothing of the package is in the repository yet."""
    ws = _worktree(tmp_path / "wt")
    main = tmp_path / "main"
    main.mkdir()
    monkeypatch.setattr(loop.verify, "run_pytest", _outcome(passed=True, failures=[], raw=""))

    report = loop.run_loop(
        ws=replace(ws, repo_root=main),
        client=FakeDrafterClient([_writes("scrape.py")]),
        brief=_brief(),
        exemplar=loop.EXEMPLAR_STRUCTURED_HTML,
        expectation_module=_expectation_module(tmp_path),
        test_paths=[Path(INVARIANTS)],
        artifacts_dir=tmp_path / "rounds",
    )
    assert report.stopped_because == "green"


def test_reserved_signatures_name_every_condition_the_loop_can_report(
    tmp_path: Path,
) -> None:
    """Task 14 branches on these; they are listed rather than recognised by eye."""
    assert set(loop.RESERVED_SIGNATURES) == {
        "no-changes",
        "deleted-in-workspace",
        "unsupported-entry",
        "wrote-outside-allowlist",
    }


def test_round_outcome_and_loop_report_take_the_contract_shape() -> None:
    outcome = loop.RoundOutcome(0, False, "sig-a", False)
    report = loop.LoopReport(rounds=[outcome], passed=False, stopped_because="green")
    assert (outcome.index, outcome.passed, outcome.signature, outcome.timed_out) == (
        0,
        False,
        "sig-a",
        False,
    )
    assert report.rounds == [outcome]
