"""Tests for the pass that decides whether a draft may be called green.

The pytest-running tests really spawn pytest. The drafter package's autouse spawn
guard denies subprocesses, and this module is the reason its allowlist now carries a
second, narrow entry: ``[sys.executable, "-m", "pytest", ...]``. The alternative was to
fake ``subprocess.run`` and assert against canned output, which would have tested this
module's *model* of pytest's exit codes -- and the defect being guarded against is a
defect in exactly that model. See ``conftest.py`` for the written-out reasoning.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import scaffold
from casesignal.drafter import verify as v

# --- the tri-state ---


def _green() -> v.TestOutcome:
    return v.TestOutcome(passed=True, failures=[], raw="")


def _red() -> v.TestOutcome:
    return v.TestOutcome(passed=False, failures=["FAILED t.py::test_x"], raw="")


def _not_run() -> v.TestOutcome:
    return v.TestOutcome(passed=False, failures=["no tests collected"], raw="", ran=False)


def test_status_is_pass_when_everything_is_green() -> None:
    assert v.resolve_status(_green(), _green(), []) is v.VerifyStatus.PASS


def test_status_is_pass_with_todos_for_optional_field_todos() -> None:
    todos = [v.Todo(field="county", line=42, text="TODO(county): narrative regex")]
    assert v.resolve_status(_green(), _green(), todos) is v.VerifyStatus.PASS_WITH_TODOS


def test_status_is_fail_when_a_required_field_has_an_unresolved_todo() -> None:
    todos = [v.Todo(field="incident_date", line=7, text="TODO(incident_date): format unknown")]
    assert v.resolve_status(_green(), _green(), todos) is v.VerifyStatus.FAIL


def test_the_required_set_is_the_four_canonical_fields() -> None:
    """The loop below iterates REQUIRED_FIELDS, so it can never notice a field being
    DROPPED from it -- it would just iterate one fewer. The set's membership is a
    contract later tasks bind to, so it is asserted literally, once."""
    assert v.REQUIRED_FIELDS == ("case_name", "source_case_id", "case_type", "incident_date")


def test_every_required_field_fails_the_draft_on_its_own() -> None:
    """The required set is a claim about four fields, not about `incident_date`."""
    for name in v.REQUIRED_FIELDS:
        todos = [v.Todo(field=name, line=1, text=f"TODO({name}): x")]
        assert v.resolve_status(_green(), _green(), todos) is v.VerifyStatus.FAIL, name


def test_status_is_fail_when_any_test_is_red() -> None:
    assert v.resolve_status(_red(), _green(), []) is v.VerifyStatus.FAIL
    assert v.resolve_status(_green(), _red(), []) is v.VerifyStatus.FAIL


def test_a_module_that_never_ran_is_not_a_pass() -> None:
    """Obligation 1: "nothing was verified" resolves to FAIL, not to green."""
    assert v.resolve_status(_not_run(), _green(), []) is v.VerifyStatus.FAIL
    assert v.resolve_status(_green(), _not_run(), []) is v.VerifyStatus.FAIL


def test_a_not_run_outcome_cannot_claim_to_have_passed() -> None:
    """The green-over-nothing state is unrepresentable rather than merely unwritten."""
    with pytest.raises(ValueError, match="did not happen"):
        v.TestOutcome(passed=True, failures=[], raw="", ran=False)


def test_the_three_verdicts_are_named_apart() -> None:
    assert _green().verdict == "green"
    assert _red().verdict == "red"
    assert _not_run().verdict == "not-run"


# --- the inventory pass's advisories (obligation 2) ---


def test_a_vacuous_floor_downgrades_a_pass() -> None:
    """A 0.0 floor renders no test at all, so a green run says nothing about that field."""
    status = v.resolve_status(_green(), _green(), [], vacuous_floors=("victim_age",))
    assert status is v.VerifyStatus.PASS_WITH_TODOS


def test_a_vacuous_floor_on_a_required_field_fails_the_draft() -> None:
    status = v.resolve_status(_green(), _green(), [], vacuous_floors=("incident_date",))
    assert status is v.VerifyStatus.FAIL


def test_an_unreachable_floor_does_not_move_the_status() -> None:
    """It predicts a red test. If the prediction holds, the red test is what fails the
    draft; using the advisory to fail OR to excuse would double-count or launder it."""
    assert (
        v.resolve_status(_green(), _green(), [], unreachable_floors=("victim_age",))
        is v.VerifyStatus.PASS
    )
    assert (
        v.resolve_status(_red(), _green(), [], unreachable_floors=("victim_age",))
        is v.VerifyStatus.FAIL
    )


def test_an_unreachable_floor_on_a_required_field_still_does_not_move_the_status() -> None:
    assert (
        v.resolve_status(_green(), _green(), [], unreachable_floors=("incident_date",))
        is v.VerifyStatus.PASS
    )


def test_build_report_consumes_all_four_advisories_from_the_brief() -> None:
    brief = {
        "coverage": {"victim_age": {"matched": 92, "total": 100, "coverage": 0.92}},
        "vacuous_floors": ["narrative"],
        "unreachable_floors": ["victim_race"],
        "suspected_page_mismatch": ["narrative"],
        "omission_rate": 0.25,
        "omitted_fields": ["photo", "contact_text"],
    }
    report = v.build_report(
        invariants=_green(), expectations=_green(), todos=[], brief=brief
    )

    assert report.status is v.VerifyStatus.PASS_WITH_TODOS
    assert report.coverage == {"victim_age": 0.92}
    assert report.vacuous_floors == ("narrative",)
    assert report.unreachable_floors == ("victim_race",)
    joined = "\n".join(report.advisories)
    # Distinctive phrasing per advisory: "narrative" alone appears in two of the four,
    # so asserting the field name would let a dropped advisory hide behind another.
    assert "assert nothing" in joined and "narrative" in joined
    assert "above their own measurement" in joined and "victim_race" in joined
    assert "wrong one" in joined  # the page-mismatch advisory
    assert "25%" in joined and "photo" in joined  # the omission advisory
    assert len(report.advisories) == 4


def test_a_malformed_coverage_entry_does_not_kill_the_report() -> None:
    """FINDING 4. Every other line in `_coverage_of` is defensive; `float()` was not."""
    brief = {
        "coverage": {
            "victim_age": {"coverage": "n/a"},
            "county": {"coverage": 0.5},
            "city": {"coverage": None},
            "narrative": True,
        }
    }
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.coverage == {"county": 0.5}


def test_a_zero_omission_rate_is_not_an_advisory() -> None:
    """The reader omitting nothing is the ordinary case, not a finding."""
    report = v.build_report(
        invariants=_green(), expectations=_green(), todos=[], brief={"omission_rate": 0.0}
    )
    assert report.advisories == ()


def test_one_module_running_red_means_something_was_verified() -> None:
    """`nothing_was_verified` is about neither module running, not about either."""
    mixed = v.build_report(invariants=_not_run(), expectations=_red(), todos=[], brief=None)
    assert mixed.status is v.VerifyStatus.FAIL
    assert mixed.nothing_was_verified is False
    assert "NOTHING WAS VERIFIED" not in mixed.summary()


def test_a_report_cannot_print_pass_next_to_the_evidence_of_its_vacuity() -> None:
    """FINDING 1. The half-informed assembly -- advisory carried, status resolved by the
    three-positional call that cannot see the brief -- is the MOST likely partial
    mistake, not the least, and it shipped a summary reading
    `PASS: ... 1 field(s) no floor can grade`."""
    green = _green()
    with pytest.raises(ValueError, match="green over something nothing graded"):
        v.VerifyReport(
            status=v.resolve_status(green, green, []),
            invariants=green,
            expectations=green,
            todos=[],
            coverage={},
            vacuous_floors=("county",),
        )


def test_a_vacuous_required_field_cannot_be_carried_under_any_green_status() -> None:
    """FINDING 1. PASS_WITH_TODOS over an ungradeable REQUIRED field is still green over
    a field nothing asserts."""
    green = _green()
    for status in (v.VerifyStatus.PASS, v.VerifyStatus.PASS_WITH_TODOS):
        with pytest.raises(ValueError, match="required"):
            v.VerifyReport(
                status=status,
                invariants=green,
                expectations=green,
                todos=[],
                coverage={},
                vacuous_floors=("incident_date",),
            )


def test_a_failing_report_may_carry_its_vacuous_floors() -> None:
    """The refusal is about green over nothing, not about recording the finding."""
    report = v.VerifyReport(
        status=v.VerifyStatus.FAIL,
        invariants=_red(),
        expectations=_green(),
        todos=[],
        coverage={},
        vacuous_floors=("incident_date", "county"),
    )
    assert report.vacuous_floors == ("incident_date", "county")


def test_pass_with_todos_over_an_optional_vacuous_field_is_allowed() -> None:
    report = v.VerifyReport(
        status=v.VerifyStatus.PASS_WITH_TODOS,
        invariants=_green(),
        expectations=_green(),
        todos=[],
        coverage={},
        vacuous_floors=("county",),
    )
    assert "no floor can grade" in report.summary()


def test_build_report_never_assembles_a_refused_pair() -> None:
    brief = {"vacuous_floors": ["county"], "floors": {"county": 0.0, "case_name": 0.95}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.status is v.VerifyStatus.PASS_WITH_TODOS


# --- FINDING 2: vacuity is read off the floors, not only off the advisory key ---


def test_a_zero_floor_is_vacuous_even_when_the_advisory_key_is_missing() -> None:
    """The advisory is a sibling key; the floors are the measurement."""
    brief = {"floors": {"county": 0.0, "case_name": 0.95}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.vacuous_floors == ("county",)
    assert report.status is v.VerifyStatus.PASS_WITH_TODOS


def test_a_zero_floor_on_a_required_field_fails_without_the_advisory_key() -> None:
    brief = {"floors": {"case_name": 0.0, "county": 0.9}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.status is v.VerifyStatus.FAIL


def test_a_malformed_advisory_key_does_not_disarm_the_floor_check() -> None:
    """`_names` returns [] for a string or a dict, which is right -- and used to be the
    only source of truth."""
    for broken in ("case_name", {"case_name": True}, None, 7):
        brief = {"vacuous_floors": broken, "floors": {"case_name": 0.0}}
        report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
        assert report.status is v.VerifyStatus.FAIL, broken


def test_the_vacuous_set_is_the_union_of_both_sources() -> None:
    brief = {"vacuous_floors": ["narrative"], "floors": {"county": 0.0, "case_name": 0.95}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.vacuous_floors == ("county", "narrative")


def test_a_real_floor_is_not_read_as_vacuous() -> None:
    brief = {"floors": {"county": 0.42, "case_name": 0.95}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.vacuous_floors == ()
    assert report.status is v.VerifyStatus.PASS


def test_a_malformed_floor_entry_costs_that_entry_and_not_the_report() -> None:
    brief = {"floors": {"county": "n/a", "case_name": None, "city": 0.0}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.vacuous_floors == ("city",)


# --- ITEM 1: a measured brief that measured nothing ---


@pytest.mark.parametrize(
    ("floors", "shape"),
    [
        (None, "absent"),
        ({}, "empty mapping"),
        ([], "list"),
        (["case_name"], "non-empty list"),
        ("case_name", "string"),
        (0.95, "a bare number"),
    ],
)
def test_a_brief_claiming_to_be_measured_must_carry_readable_floors(
    floors: object, shape: str
) -> None:
    """"Route the status through build_report" is necessary and NOT sufficient: every
    one of these satisfies the rule and resolves PASS, because a floors block that yields
    no names yields no vacuity either."""
    brief: dict[str, object] = {"inventory_measured": True}
    if floors is not None:
        brief["floors"] = floors
    with pytest.raises(v.UnusableBrief, match="nothing actually measured"):
        v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)


def test_a_healthy_measured_brief_is_not_refused() -> None:
    brief = {"inventory_measured": True, "floors": {"case_name": 0.95, "county": 0.4}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.status is v.VerifyStatus.PASS


def test_the_refusal_fires_only_on_the_measured_claim() -> None:
    """A partial or caller-assembled brief never claims measurement; refusing those would
    break every legitimate call that hands this function what it happens to have."""
    briefs: tuple[dict[str, Any], ...] = (
        {},
        {"floors": {}},
        {"inventory_measured": False},
        {"omission_rate": 0.0},
    )
    for brief in briefs:
        report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
        assert report.status is v.VerifyStatus.PASS, brief


def test_the_unusable_brief_refusal_is_the_generators_own_refusal() -> None:
    """Same condition, different layer: a caller already handling the generator's refusal
    handles this one."""
    assert issubclass(v.UnusableBrief, scaffold.UnmeasuredBrief)


def test_an_all_zero_floors_block_is_handled_by_the_vacuity_path_not_the_refusal() -> None:
    brief = {"inventory_measured": True, "floors": {"county": 0.0, "city": 0.0}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.status is v.VerifyStatus.PASS_WITH_TODOS
    assert report.vacuous_floors == ("city", "county")


# --- ITEM 2: a boolean floor ---


def test_a_boolean_floor_is_vacuous_rather_than_unparseable() -> None:
    """`floors: {case_name: false}` used to resolve PASS. The bool exclusion was written
    for coverage figures, where "True is a bad coverage figure" is right; reused for
    floors it fails in the green direction."""
    brief = {"floors": {"case_name": False, "county": 0.9}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.vacuous_floors == ("case_name",)
    assert report.status is v.VerifyStatus.FAIL


def test_a_true_floor_is_vacuous_too() -> None:
    """`True` floats to 1.0, which would read as the strictest floor in the file. A floor
    nobody can read grades nothing in either direction."""
    brief = {"floors": {"county": True, "case_name": 0.95}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.vacuous_floors == ("county",)
    assert report.status is v.VerifyStatus.PASS_WITH_TODOS


def test_a_boolean_coverage_figure_is_still_not_a_coverage_figure() -> None:
    """Item 2 changes the FLOORS judgment only; `True` remains a bad coverage number."""
    brief = {"coverage": {"county": True, "city": {"coverage": 0.5}}}
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=brief)
    assert report.coverage == {"city": 0.5}


def test_forgetting_the_brief_is_unwriteable() -> None:
    """`brief` has no default, so a caller's SILENCE -- which is exactly the uninformed
    hole -- is a TypeError instead of a PASS. It cannot make a wrong answer impossible;
    it makes "I forgot the brief" impossible to write."""
    with pytest.raises(TypeError, match="brief"):
        v.build_report(invariants=_green(), expectations=_green(), todos=[])  # type: ignore[call-arg]


def test_the_refusal_chain_reaches_the_generators_own_refusal_base() -> None:
    """UnusableBrief -> UnmeasuredBrief -> ScaffoldRefusal -> ValueError. Recorded because
    an orchestrator mapping ScaffoldRefusal to "the scaffold pass refused" will
    misattribute a VERIFY-stage refusal; the mapping has to be stage-aware."""
    chain = [cls.__name__ for cls in v.UnusableBrief.__mro__]
    assert chain[:4] == [
        "UnusableBrief",
        "UnmeasuredBrief",
        "ScaffoldRefusal",
        "ValueError",
    ]


def test_an_explicit_none_brief_is_still_a_plain_pass() -> None:
    """This module cannot tell "no brief exists for this run" from "the caller forgot",
    so refusing silence would be a guess. The refusal fires only on a positive false
    claim -- inventory_measured: true over floors that say nothing."""
    report = v.build_report(invariants=_green(), expectations=_green(), todos=[], brief=None)
    assert report.status is v.VerifyStatus.PASS
    assert report.advisories == ()
    assert report.coverage == {}


def test_the_report_distinguishes_nothing_verified_from_everything_red() -> None:
    nothing = v.build_report(invariants=_not_run(), expectations=_not_run(), todos=[], brief=None)
    everything_red = v.build_report(invariants=_red(), expectations=_red(), todos=[], brief=None)

    assert nothing.status is everything_red.status is v.VerifyStatus.FAIL
    assert nothing.nothing_was_verified is True
    assert everything_red.nothing_was_verified is False
    assert "NOTHING WAS VERIFIED" in nothing.summary()
    assert "NOTHING WAS VERIFIED" not in everything_red.summary()


# --- TODO classification (obligations 4, 6, 7) ---


def test_find_todos_extracts_the_field_from_the_marker(tmp_path: Path) -> None:
    mod = tmp_path / "transform.py"
    mod.write_text("x = 1\n# TODO(county): no county in the narrative\ny = 2\n")
    todos = v.find_todos(mod)
    assert todos == [v.Todo(field="county", line=2, text="TODO(county): no county in the narrative")]


def test_find_todos_ignores_unmarked_todos(tmp_path: Path) -> None:
    mod = tmp_path / "transform.py"
    mod.write_text("# TODO clean this up later\n")
    assert v.find_todos(mod) == []


def test_find_todos_requires_the_colon_that_makes_it_a_claim(tmp_path: Path) -> None:
    """`TODO(county)` without the colon is prose about a field, not a claim about one."""
    mod = tmp_path / "transform.py"
    mod.write_text("# TODO(county) maybe\n# TODO(city): really\n")
    assert [todo.field for todo in v.find_todos(mod)] == ["city"]


def test_find_todos_raises_rather_than_reporting_a_missing_module_as_clean(
    tmp_path: Path,
) -> None:
    """Obligation 6: no transform.py means no parser, which is louder than no TODOs."""
    with pytest.raises(v.TransformNotDrafted, match="no parser at all"):
        v.find_todos(tmp_path / "transform.py")


def test_a_missing_module_is_still_catchable_as_a_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        v.find_todos(tmp_path / "transform.py")


def test_two_markers_on_one_line_are_two_claims(tmp_path: Path) -> None:
    """FINDING 3. `search` kept only the first, so a line carrying an optional field and
    a required one reported the optional one and resolved the draft green."""
    mod = tmp_path / "transform.py"
    mod.write_text("# TODO(county): a  TODO(case_name): b\n")
    todos = v.find_todos(mod)
    assert [todo.field for todo in todos] == ["county", "case_name"]
    assert todos[0].text == "TODO(county): a"
    assert v.resolve_status(_green(), _green(), todos) is v.VerifyStatus.FAIL


@pytest.mark.parametrize(
    "line",
    [
        "# TODO(Case_Name): mixed case",
        "# todo(case_name): lower case",
        "# TODO (case_name): a space before the paren",
        "# TODO( case_name ): padded",
        "# TODO(case_name) : a space before the colon",
    ],
)
def test_the_near_miss_marker_shapes_are_accepted_rather_than_dropped(
    tmp_path: Path, line: str
) -> None:
    """FINDING 3. Every near miss fails in the same direction, and that direction is
    green: an ignored marker on a required field is a draft that passes."""
    mod = tmp_path / "transform.py"
    mod.write_text(line + "\n")
    todos = v.find_todos(mod)
    assert [todo.field for todo in todos] == ["case_name"], line
    assert v.resolve_status(_green(), _green(), todos) is v.VerifyStatus.FAIL


def test_widening_the_marker_did_not_swallow_the_unmarked_form(tmp_path: Path) -> None:
    """The near-miss widening must not reach the ambient `# TODO fix this`."""
    mod = tmp_path / "transform.py"
    mod.write_text("# TODO clean this up later\n# todo: soon\n# TODO(county) maybe\n")
    assert v.find_todos(mod) == []


def test_the_digest_marker_line_is_excluded_from_the_scan(tmp_path: Path) -> None:
    """Obligation 7: the generator's trailing marker is not source the parser wrote."""
    body = "x = 1\n# TODO(county): missing\n"
    stamped = scaffold.stamp_generated(
        body, path="transform.py", session_id="s", captured_at="t"
    )
    mod = tmp_path / "transform.py"
    mod.write_text(stamped)

    todos = v.find_todos(mod)
    assert [todo.line for todo in todos] == [2]
    # The marker is the last line and is not scanned; a count off the scan excludes it.
    assert len(v._scannable_lines(stamped)) == len(stamped.splitlines()) - 1


def test_a_file_without_a_marker_keeps_every_line(tmp_path: Path) -> None:
    text = "a = 1\nb = 2\n"
    assert v._scannable_lines(text) == ["a = 1", "b = 2"]


def test_todo_line_numbers_are_physical_lines(tmp_path: Path) -> None:
    mod = tmp_path / "transform.py"
    mod.write_text("\n\n\n# TODO(city): x\n")
    assert v.find_todos(mod)[0].line == 4


# --- run_pytest, against real pytest (obligations 1 and 3) ---


def _module(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_run_pytest_reports_failures(tmp_path: Path) -> None:
    test_file = _module(
        tmp_path,
        "test_sample.py",
        "def test_a():\n    assert True\n\ndef test_b():\n    assert False\n",
    )
    outcome = v.run_pytest([test_file], cwd=tmp_path)
    assert outcome.passed is False
    assert outcome.ran is True
    assert outcome.returncode == 1
    assert any("test_b" in failure for failure in outcome.failures)


def test_run_pytest_reports_a_green_module(tmp_path: Path) -> None:
    test_file = _module(tmp_path, "test_ok.py", "def test_a():\n    assert True\n")
    outcome = v.run_pytest([test_file], cwd=tmp_path)
    assert outcome.passed is True
    assert outcome.ran is True
    assert outcome.failures == []


def test_an_empty_collection_is_not_a_pass(tmp_path: Path) -> None:
    """pytest exits 5 when nothing is collected. Read as 'non-zero == failed' it looks
    like a red run; read as 'zero == passed' inverted it looks green. It is neither."""
    test_file = _module(tmp_path, "test_empty.py", "x = 1\n")
    outcome = v.run_pytest([test_file], cwd=tmp_path)

    assert outcome.returncode == 5
    assert outcome.ran is False
    assert outcome.passed is False
    assert any("no tests collected" in failure for failure in outcome.failures)


def test_a_module_that_cannot_be_imported_did_not_run(tmp_path: Path) -> None:
    test_file = _module(
        tmp_path, "test_broken.py", "import a_module_that_does_not_exist\n\ndef test_a():\n    pass\n"
    )
    outcome = v.run_pytest([test_file], cwd=tmp_path)

    assert outcome.ran is False
    assert outcome.passed is False
    assert outcome.returncode == 2


def test_an_erroring_fixture_is_reported_as_a_failure(tmp_path: Path) -> None:
    """pytest files a fixture blow-up under ERROR, not FAILED. A parser that read only
    FAILED lines would report a red run that named nothing."""
    test_file = _module(
        tmp_path,
        "test_fixture.py",
        "import pytest\n\n\n@pytest.fixture\ndef broken():\n    raise RuntimeError('boom')\n"
        "\n\ndef test_a(broken):\n    assert True\n",
    )
    outcome = v.run_pytest([test_file], cwd=tmp_path)

    assert outcome.ran is True
    assert outcome.passed is False
    assert any(failure.startswith("ERROR") and "test_a" in failure for failure in outcome.failures)


def test_rc_1_that_names_no_failing_test_did_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rc 1 that names no failing test is not a completed run, and must not grade as one.

    `-rfE` is passed explicitly, so a genuine failing test always emits a FAILED/ERROR
    summary line; rc 1 with none of them is an interpreter or an environment that failed
    before pytest reported anything. It used to come back `ran=True` with the verdict
    "pytest exited 1 but named no failing test" -- an environment failure graded as a red
    test round, on the flag `build_report` uses to say a module did not run at all.
    """

    class Completed:
        returncode = 1
        stdout = "nothing that looks like a summary line\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Completed())
    outcome = v.run_pytest([tmp_path / "test_x.py"], cwd=tmp_path)

    assert outcome.ran is False
    assert outcome.passed is False
    assert outcome.failures and "not a completed run" in outcome.failures[0]


def test_a_missing_environment_variable_is_refused_and_named_as_the_environment(
    tmp_path: Path,
) -> None:
    """The one failure the allowlist can produce that the draft cannot.

    Returned as a round outcome it is misattributed twice over: the rc-2 verdict names
    the generated module as the suspect, and `redact` feeds that text to the NEXT agent,
    so an operator's shell buys paid rounds to fix itself. Raised, it stops the loop and
    says whose problem it is.
    """
    module = _module(
        tmp_path,
        "test_needs_env.py",
        "import os\ndef test_a():\n    assert os.environ['CASESIGNAL_NOT_ON_THE_ALLOWLIST']\n",
    )

    with pytest.raises(v.MissingGradingEnvironment) as caught:
        v.run_pytest([module], cwd=tmp_path)

    message = str(caught.value)
    assert "CASESIGNAL_NOT_ON_THE_ALLOWLIST" in message
    assert "_INHERITED_ENV" in message
    assert "not the draft" in message


def test_a_data_key_error_is_not_mistaken_for_the_environment(tmp_path: Path) -> None:
    """Both halves are required: an upper-snake KeyError alone is ordinary parser output.

    A generated transform indexing a record by an upper-case key raises exactly the
    shape the environment detector looks for, and refusing the whole draft for one would
    be the misattribution running the other way.
    """
    module = _module(
        tmp_path,
        "test_data_key.py",
        "def test_a():\n    record = {'case_name': 'x'}\n    assert record['SOURCE_CASE_ID']\n",
    )

    outcome = v.run_pytest([module], cwd=tmp_path)

    assert outcome.ran is True
    assert outcome.passed is False


def test_every_not_ran_verdict_points_at_the_allowlist_as_a_candidate_cause() -> None:
    """The rc-2 text names the generated module; without this it names only that."""
    for code in (v._EXIT_INTERRUPTED, v._EXIT_INTERNAL_ERROR, v._EXIT_USAGE_ERROR):
        assert "_INHERITED_ENV" in v._NOT_RAN_REASONS[code]
    assert "_INHERITED_ENV" in v._NO_TEST_NAMED_AT_RC_1


def test_run_pytest_refuses_an_empty_path_list(tmp_path: Path) -> None:
    """An empty list would fall back to `testpaths` and run the whole repository."""
    with pytest.raises(v.NoTestPaths, match="entire"):
        v.run_pytest([], cwd=tmp_path)


def test_run_pytest_does_not_inherit_the_outer_runs_addopts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--this-option-does-not-exist")
    test_file = _module(tmp_path, "test_ok.py", "def test_a():\n    assert True\n")
    outcome = v.run_pytest([test_file], cwd=tmp_path)
    assert outcome.passed is True, outcome.raw


def test_the_grading_subprocess_does_not_inherit_the_operators_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This subprocess imports and runs modules an unattended agent wrote.

    It also runs them with the repository's DB-guard conftest replaced, because that
    guard exits 4 on every round. Executing the agent's code is inherent to the design;
    handing it `DATABASE_URL` and every API key in the operator's shell is not, and it
    is the half that is free to close. Run for real, not against a fake env dict.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://live-production/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-real-key")
    test_file = _module(
        tmp_path,
        "test_env.py",
        "import os\n"
        "def test_a():\n"
        "    assert os.environ.get('DATABASE_URL') is None\n"
        "    assert os.environ.get('ANTHROPIC_API_KEY') is None\n"
        "    assert os.environ.get('AWS_SECRET_ACCESS_KEY') is None\n",
    )

    outcome = v.run_pytest([test_file], cwd=tmp_path)

    assert outcome.passed is True, outcome.raw


def test_the_grading_subprocess_still_gets_the_worktree_on_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PYTHONPATH is load-bearing, not convenience.

    Both callers set it through `cli._worktree_on_the_path` so the child imports the
    parser out of the WORKTREE. Dropped, the child imports the scaffolded stub from the
    operator's editable install and grades the agent's work by a module it never wrote.
    """
    package = tmp_path / "src_dir"
    package.mkdir()
    (package / "drafted_marker.py").write_text("VALUE = 'from the worktree'\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(package))
    test_file = _module(
        tmp_path,
        "test_path.py",
        "import drafted_marker\ndef test_a():\n    assert drafted_marker.VALUE\n",
    )

    assert v.run_pytest([test_file], cwd=tmp_path).passed is True


def test_a_grading_run_with_no_path_refuses_rather_than_limping_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verdict off a run that could not start properly is not a verdict about the draft."""
    monkeypatch.delenv("PATH", raising=False)
    with pytest.raises(v.MissingGradingEnvironment, match="PATH"):
        v.run_pytest([tmp_path / "test_x.py"], cwd=tmp_path)


def test_a_timeout_did_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1.0, output=b"partial")

    monkeypatch.setattr(subprocess, "run", explode)
    outcome = v.run_pytest([tmp_path / "test_x.py"], cwd=tmp_path)

    assert outcome.ran is False
    assert outcome.passed is False
    assert "timed out" in outcome.failures[0]
    assert "partial" in outcome.raw


def test_run_pytest_goes_through_the_module_level_subprocess_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `runner=subprocess.run` default argument would be bound at import and would
    silently escape the package's spawn guard. This pins the late lookup."""
    seen: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake(cmd: list[str], **kwargs: object) -> Completed:
        seen.append(cmd)
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake)
    v.run_pytest([tmp_path / "test_x.py"], cwd=tmp_path)

    assert seen and seen[0][:3] == [sys.executable, "-m", "pytest"]
    assert "-p" in seen[0] and "no:cacheprovider" in seen[0]


# --- the request budget (obligation 5) ---


class _Client:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> str:
        self.urls.append(url)
        return "ok"


def test_request_budget_raises_past_the_cap() -> None:
    budgeted = v.RequestBudget(_Client(), limit=2)
    budgeted.get("https://x/1")
    budgeted.get("https://x/2")
    with pytest.raises(v.BudgetExceeded, match="2"):
        budgeted.get("https://x/3")


def test_the_refused_request_is_never_made() -> None:
    """A counter incremented after a successful call caps the count, not the traffic."""
    client = _Client()
    budgeted = v.RequestBudget(client, limit=1)
    budgeted.get("https://x/1")
    with pytest.raises(v.BudgetExceeded):
        budgeted.get("https://x/2")
    assert client.urls == ["https://x/1"]


def test_the_budget_tracks_what_it_spent() -> None:
    budgeted = v.RequestBudget(_Client(), limit=3)
    budgeted.get("https://x/1")
    assert budgeted.spent == 1
    assert budgeted.remaining == 2
    assert budgeted.calls == (("get", "https://x/1"),)


def test_a_zero_budget_refuses_the_first_request() -> None:
    with pytest.raises(v.BudgetExceeded):
        v.RequestBudget(_Client(), limit=0).get("https://x/1")


def test_a_negative_budget_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="negative"):
        v.RequestBudget(_Client(), limit=-1)


def test_the_wrapper_offers_no_uncounted_route_to_the_client() -> None:
    """No __getattr__ passthrough: a cap reachable around is not a cap."""
    budgeted = v.RequestBudget(_Client(), limit=1)
    with pytest.raises(AttributeError):
        _ = budgeted.urls  # type: ignore[attr-defined]
    assert not hasattr(budgeted, "_client")


def test_every_request_verb_is_charged_to_the_same_budget() -> None:
    class Multi:
        def get(self, url: str) -> str:
            return "g"

        def head(self, url: str) -> str:
            return "h"

        def post(self, url: str) -> str:
            return "p"

        def fetch_to_file(self, url: str) -> str:
            return "f"

    budgeted = v.RequestBudget(Multi(), limit=3)
    budgeted.get("https://x/1")
    budgeted.head("https://x/2")
    budgeted.post("https://x/3")
    with pytest.raises(v.BudgetExceeded):
        budgeted.fetch_to_file("https://x/4")


def test_the_budget_delegates_rather_than_reimplementing_the_request() -> None:
    """Every SSRF check lives in the wrapped client and is reached untouched. A wrapper
    that answered a request itself would be a wrapper that skipped the allowlist."""
    refusals: list[str] = []

    class Refusing:
        def get(self, url: str) -> str:
            refusals.append(url)
            raise RuntimeError("polite_http refuses non-allowlisted host")

    budgeted = v.RequestBudget(Refusing(), limit=5)
    with pytest.raises(RuntimeError, match="non-allowlisted"):
        budgeted.get("http://169.254.169.254/latest/meta-data/")
    assert refusals == ["http://169.254.169.254/latest/meta-data/"]


def test_a_client_missing_a_verb_says_so_rather_than_pretending() -> None:
    budgeted = v.RequestBudget(_Client(), limit=2)
    with pytest.raises(AttributeError, match="wraps a client"):
        budgeted.post("https://x/1")
    assert budgeted.spent == 0


def test_calls_records_attempts_including_refused_ones() -> None:
    """FINDING 5. The charge precedes the delegate, so a request the client refuses is
    still counted -- correct (a paginator looping on refusals must exhaust its budget),
    but it means `calls` is not a log of successes."""

    class Refusing:
        def get(self, url: str) -> str:
            raise RuntimeError("polite_http refuses non-allowlisted host")

    budgeted = v.RequestBudget(Refusing(), limit=2)
    with pytest.raises(RuntimeError):
        budgeted.get("http://169.254.169.254/")
    assert budgeted.calls == (("get", "http://169.254.169.254/"),)
    assert budgeted.spent == 1


def test_the_budget_closes_the_client_it_wrapped() -> None:
    class Closable(_Client):
        closed = False

        def close(self) -> None:
            self.closed = True

    client = Closable()
    with v.RequestBudget(client, limit=1) as budgeted:
        budgeted.get("https://x/1")
    assert client.closed is True


# --- the contract ---


def test_verify_status_is_not_named_status() -> None:
    """`casesignal.scout.models.Status` already exists and the finishing task imports
    both; a collision between them would be resolved by import order."""
    assert not hasattr(v, "Status")
    assert {member.name for member in v.VerifyStatus} == {
        "PASS",
        "PASS_WITH_TODOS",
        "FAIL",
    }


def test_the_report_binds_to_the_five_field_contract() -> None:
    report = v.VerifyReport(
        status=v.VerifyStatus.PASS,
        invariants=_green(),
        expectations=_green(),
        todos=[v.Todo(field="county", line=1, text="TODO(county): x")],
        coverage={"victim_age": 0.92},
    )
    assert report.unreachable_floors == () and report.vacuous_floors == ()
    assert report.advisories == ()
