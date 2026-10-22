"""The pass that decides whether a draft may be called green — and what green means.

Everything upstream exists so that the word this module prints means something. The
capture pass refuses a corpus it cannot identify; the reader pass is denied the golden
values; the inventory pass derives its floors from the records rather than accepting an
agent's declaration of them; the scaffold pass refuses an unmeasured brief. All of it is
in service of one sentence at the end of a run, and a status that reads green over an
unverified adapter is the single failure the whole design was built to prevent.

What this module does NOT do
----------------------------
Verification runs the two generated modules against captured responses: shared
source traversal, joined parser output, pure canonical mapping, and adapter stage
wiring. It does not certify database persistence or a live production ingestion.
Grading requires Linux Landlock ABI 3+ and libseccomp, confines filesystem access,
disables network/process creation, and requires executed, non-skipped test results.
This contains generated code; it does not make same-process pytest results tamper
proof against deliberately adversarial code. Human code review remains required.

Three outcomes for a test run, not two
--------------------------------------
"Red" and "green" do not cover it. A generated module that cannot be imported, whose
collection errors, or that contains no tests at all was not verified — nothing was
asserted and nothing failed. ``pytest`` reports that distinctly (exit 5 for nothing
collected, 2 for an interrupted collection, 3 for an internal error, 4 for a usage
error), and this repository has already been bitten once by a harness that read a
non-zero exit as success. So :class:`TestOutcome` carries ``ran`` alongside ``passed``,
``passed=True`` with ``ran=False`` is refused at construction, and the tri-state resolves
a not-ran outcome to ``FAIL`` — not because a test went red, but because the claim
"verified" cannot be made. ``TestOutcome.verdict`` says which of the three it was.

The status is exactly three values
----------------------------------
``PASS``; ``PASS_WITH_TODOS``, green but carrying unresolved work on optional fields; and
``FAIL``. There is no fourth for "did not run", because "did not run" is not a shade of
green — it is the absence of evidence, and the absence of evidence resolves to the same
place a red test does.

What the marked TODO convention buys
------------------------------------
The parser pass is instructed to leave ``TODO(field): reason`` where it could not extract
a field, and :func:`find_todos` keys on exactly that form. A bare ``TODO`` is ignored on
purpose: unmarked TODOs are ambient in any codebase, and a classifier that counted them
would resolve every draft to ``PASS_WITH_TODOS`` regardless of the draft, which is the
same as classifying nothing. The marker is a machine-readable claim by the agent about a
named field, and it is graded as one — a marked TODO on a canonical field the pipeline
cannot do without (:data:`REQUIRED_FIELDS`) is a ``FAIL``, and on any other field it is
the difference between ``PASS`` and ``PASS_WITH_TODOS``.

Consuming the inventory pass's advisories
-----------------------------------------
:class:`casesignal.drafter.inventory.Measurement` carries four advisory findings, and an
advisory nothing consumes is decoration. Two of them bear on this decision and are
treated very differently, for one reason:

``vacuous_floors`` **moves the status**. A NARRATIVE field whose measured coverage sat at
or below the tolerance derives a floor of exactly 0.0, the scaffold renders no coverage
test for it at all, and no parser can ever fail it — including one that extracts the
field never. There is no red-test route by which that field could be caught, so if this
module stayed silent the field would be unverified underneath a green word. That is the
prevented failure, verbatim. A vacuous floor therefore degrades ``PASS`` to
``PASS_WITH_TODOS``, and on a field in :data:`REQUIRED_FIELDS` it is a ``FAIL`` on the
same ground as a required TODO: nothing asserts the field.

``unreachable_floors`` **does not move the status**, and it is worth being precise about
why, because the tempting reading is backwards. An unreachable floor is a prediction that
a rendered test will be red from its first run. If the prediction holds, the test IS red,
the run reports it, and ``FAIL`` is reached by the honest route — an actually failing
assertion. Using the advisory to force ``FAIL`` would double-count that; using it to
EXCUSE the red ("known to be unreachable, so not really a failure") would be exactly the
green-over-unverified move, dressed as leniency. And the prediction can simply be wrong:
the floor was derived from a locator, the test grades a parser, and a parser that reads
the field correctly can clear a floor the locator could not. So it is carried into the
report as attribution — it tells an operator staring at a red coverage test to suspect
the locator rather than the parser — and it changes nothing about the verdict.

``suspected_page_mismatch`` and ``omission_rate`` are rendered as advisory text only.
Neither is evidence about what was verified: the first says a locator was probably filed
under the wrong page, which is a re-read instruction, and the second says the reader
omitted fields nobody has claimed are required.

The request budget lives below the adapter
------------------------------------------
Pagination is inside generated code. A page cap passed as a parameter is a cap the
adapter is trusted to honour, and the entire premise of this pipeline is that generated
code is not trusted until it is verified — trusting it to bound its own live traffic
during the pass that verifies it is circular. :class:`RequestBudget` therefore wraps the
HTTP client and refuses past the cap, one level below anything the draft can reach.

It is a budget guard and not a sandbox, and the difference is worth stating: it does not
and cannot stop code that constructs its own client. What it does is make an unbounded
crawl impossible for a draft that was HANDED a client, which is the realistic failure —
a paginator with a wrong termination condition walking a publisher's site all night.

It also weakens nothing about the SSRF defense, because it reimplements no part of it.
Every call is delegated to :class:`casesignal.etl.services.polite_http.PoliteHTTPClient`
untouched, so the allowlist, the private/loopback/link-local/reserved and bare-public
IP-literal rejections, the DNS-rebinding resolve guard and the per-redirect-hop
revalidation all still run, in that order, on every request. The wrapper adds a refusal;
it removes none. It deliberately exposes no ``__getattr__`` passthrough and keeps the
wrapped client under a name-mangled attribute, so a draft handed a budgeted client cannot
reach an uncounted method by accident.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from casesignal.drafter.scaffold import UnmeasuredBrief, is_marker_line

__all__ = [
    "BudgetExceeded",
    "DEFAULT_LIVE_REQUESTS",
    "NoTestPaths",
    "REQUIRED_FIELDS",
    "RequestBudget",
    "TestOutcome",
    "Todo",
    "TransformNotDrafted",
    "UnusableBrief",
    "VerifyReport",
    "VerifyStatus",
    "build_report",
    "find_todos",
    "resolve_status",
    "run_pytest",
]

# The canonical fields the load and transform stages cannot do without. An unresolved
# marked TODO on any of them, or a floor on any of them that asserts nothing, is a FAIL
# rather than a note: a record with no name is not a case, a record with no id collapses
# against its neighbours at load, a record with no case_type falls through to the generic
# bucket and loses what the source said, and a record with no incident_date cannot be
# placed on the only axis the whole platform sorts by.
REQUIRED_FIELDS: tuple[str, ...] = (
    "case_name",
    "source_case_id",
    "case_type",
    "incident_date",
)

# What --live-check may spend when the operator names no number. Small on purpose: the
# live probe exists to answer "is the source still shaped the way the capture found it",
# which the first page answers, and every request past that is spent against a
# publisher who did not ask to be crawled twice.
DEFAULT_LIVE_REQUESTS = 5

# pytest's documented exit codes. Named because the whole point of this module is that
# `returncode != 0` is not one condition but four different ones, and only ONE of them
# means "a test failed".
_EXIT_OK = 0
_EXIT_TESTS_FAILED = 1
_EXIT_INTERRUPTED = 2
_EXIT_INTERNAL_ERROR = 3
_EXIT_USAGE_ERROR = 4
_EXIT_NO_TESTS_COLLECTED = 5

# Appended to every not-ran verdict. The grading subprocess runs on a fixed environment
# allowlist, so a name the operator's shell carries and the child's does not is one of
# the ordinary causes of a round that did not run -- and it is the cause the rest of the
# verdict text actively points away from, since it names the generated module as the
# suspect. Said in the verdict because the verdict is what an operator reads out of the
# round artifacts, and because it is what `redact` feeds the NEXT agent: a paid round
# spent fixing the operator's shell is the failure this sentence exists to prevent.
_NOT_RAN_ENV_NOTE = (
    " If the raw output names an environment variable, that is this pipeline's grading "
    "allowlist (verify._INHERITED_ENV) and not the draft"
)

_NOT_RAN_REASONS: Mapping[int, str] = {
    _EXIT_INTERRUPTED: (
        "pytest exited 2 (interrupted): collection failed, usually an ImportError in a "
        "generated module. Nothing was verified" + _NOT_RAN_ENV_NOTE
    ),
    _EXIT_INTERNAL_ERROR: (
        "pytest exited 3 (internal error). Nothing was verified" + _NOT_RAN_ENV_NOTE
    ),
    _EXIT_USAGE_ERROR: (
        "pytest exited 4 (usage error): the paths or options were wrong. Nothing was "
        "verified" + _NOT_RAN_ENV_NOTE
    ),
    _EXIT_NO_TESTS_COLLECTED: (
        "pytest exited 5 (no tests collected). The module imported and asserted "
        "nothing; this is not a pass"
    ),
}

# rc 1 is "a test failed" ONLY when a test was named. An interpreter that could not
# start -- a broken PYTHONPATH, a missing shared library, a `python -m pytest` that never
# reached pytest -- also exits 1, with nothing on stdout, and was being graded as a red
# round: `ran=True`, `passed=False`, and a verdict reading "pytest exited 1 but named no
# failing test". A failed interpreter is not a completed run, and the difference is not
# cosmetic: `ran` is what `build_report` uses to say "this module did not run at all",
# and a draft can be marked red for a machine that never executed it.
#
# Safe by construction in the other direction too: `-rfE` is passed explicitly, so a
# genuine failing test always emits a FAILED/ERROR summary line. rc 1 with none of them
# is not a pytest run that produced results.
_NO_TEST_NAMED_AT_RC_1 = (
    "pytest exited 1 without naming a failing test, which is not a completed run: the "
    "interpreter or its environment failed before pytest reported anything. Nothing was "
    "verified" + _NOT_RAN_ENV_NOTE
)

# A missing environment variable, as the child reports it. Both halves are required --
# an upper-snake name in a KeyError AND an environment access in the same output -- so a
# generated transform raising KeyError on an upper-case DATA key does not read as this.
_ENV_KEY_ERROR = re.compile(r"KeyError: ['\"]([A-Z][A-Z0-9_]{2,})['\"]")
_ENV_ACCESS_MARKERS = ("os.environ", "environ[", "getenv", "environb")

# The short-summary lines pytest emits for a failing or erroring node. `-rfE` is passed
# explicitly rather than relied upon so the format does not depend on the invoking
# configuration. The whole line is kept, detail included, because Task 13's redactor
# needs the assertion text to strip the golden values out of it.
_FAILURE_LINE = re.compile(r"^(?:FAILED|ERROR)\s+\S+.*$", re.MULTILINE)

# The parser pass's marked-TODO convention: a field name in parentheses and a colon.
# Requiring the colon is what separates a claim about a named field from the ambient
# `# TODO clean this up` that every codebase carries.
#
# The near-miss shapes are ACCEPTED rather than ignored, because every one of them fails
# in the same direction and that direction is green: `TODO(Case_Name):`, `TODO (case_name):`
# and `todo(case_name):` are all a drafting agent making a claim about a required field,
# and an anchored case-sensitive pattern turns each of them into no TODO at all -- which
# is to say into a PASS. Over-reporting is the safe error here and under-reporting is
# not, which is the same reason a marker inside a string literal is counted. The captured
# name is lower-cased so `TODO(Case_Name):` is graded against REQUIRED_FIELDS as the
# field it plainly means.
_TODO_MARKER = re.compile(r"TODO\s*\(\s*(?P<field>[A-Za-z][A-Za-z0-9_]*)\s*\)\s*:", re.IGNORECASE)

# What the grading subprocess is allowed to inherit. An ALLOWLIST, and the inversion is
# the point: this subprocess runs code an unattended agent wrote, and the worktree
# conftest that lets it run at all is the repository's test conftest with the
# test-database redirection and its sentinel enforcement taken out. Handing that
# `DATABASE_URL` and every API key in the operator's shell is a widening nothing here
# needs -- executing the agent's code is inherent to the design, giving it the
# operator's credentials is not. Under a denylist the default was inherit, so every
# secret anybody ever adds to a shell profile is inherited until someone remembers to
# name it here; under an allowlist the default is drop.
#
# What survives is what a pytest run needs to start and to find the code under test,
# and nothing that authenticates to anything:
#
# - ``PATH`` -- required; see :class:`MissingGradingEnvironment`.
# - ``PYTHONPATH`` -- load-bearing rather than convenient. Both callers set it through
#   ``cli._worktree_on_the_path`` so the child imports the parser out of the WORKTREE;
#   without it the child imports the scaffolded stub from the operator's editable
#   install and grades the agent's work by a module it never wrote.
# - ``HOME`` / ``USERPROFILE``, ``TMPDIR`` / ``TEMP`` / ``TMP`` -- where Python and
#   pytest put per-user and temporary files.
# - ``SYSTEMROOT`` / ``COMSPEC`` / ``PATHEXT`` / ``WINDIR`` -- Windows needs these to
#   start a process at all. This project runs from WSL against Windows tooling.
# - ``VIRTUAL_ENV``, ``PYTHONIOENCODING``, ``LANG``, ``LC_ALL``, ``LC_CTYPE`` -- the
#   interpreter's own environment and its text decoding.
#
# Deliberately NOT here, beyond every secret: ``PYTEST_ADDOPTS`` and ``PYTEST_PLUGINS``
# would silently reshape the child run, and ``PYTEST_CURRENT_TEST`` names a test in the
# OUTER process, which pytest reports in crash tracebacks and which would then be a lie.
_INHERITED_ENV = (
    "PATH",
    "PYTHONPATH",
    "HOME",
    "USERPROFILE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "VIRTUAL_ENV",
    "PYTHONIOENCODING",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
)

# Without which there is no run to grade. Missing means something has gone wrong with
# the environment this process itself was started in, and a grading round that quietly
# limps on from there reports a verdict about a run that never happened properly.
_REQUIRED_ENV = ("PATH",)


class VerifyStatus(Enum):
    """The three things a verified draft can be.

    Named ``VerifyStatus`` and not ``Status`` because
    :class:`casesignal.scout.models.Status` already exists and the finishing task imports
    both: one is the drafter's judgment about a run, the other is the registry's
    lifecycle state for a candidate, and a name collision between them would be resolved
    by import order.
    """

    PASS = "PASS"
    PASS_WITH_TODOS = "PASS_WITH_TODOS"
    FAIL = "FAIL"


class MissingGradingEnvironment(RuntimeError):
    """Raised when the environment the grading subprocess needs is not there.

    Loud rather than lenient, and it is the one direction that matters: a grading run
    started with a broken environment produces a verdict about a run that never happened
    properly, and a red module is indistinguishable from a red parser.

    Two triggers. Before the spawn, a name in :data:`_REQUIRED_ENV` that this process
    does not have. After it, a child that died on an environment variable the allowlist
    dropped — which is the failure mode the allowlist itself introduced, and the reason
    it is safe to have one: returned as an ordinary round it comes back as a red or
    not-ran verdict whose text names the GENERATED MODULE as the suspect, and `redact`
    then feeds that to the next paid agent, so the operator's shell buys rounds to fix
    itself. ``cli.stage_of`` maps this to its own ``environment`` stage rather than to
    any pass, because no pass is at fault and re-running one cannot help.
    """


def _grading_environment() -> dict[str, str]:
    """The minimum environment the grading subprocess runs under.

    See :data:`_INHERITED_ENV` for what is kept and why. Everything else -- the
    operator's ``DATABASE_URL``, every API key in their shell -- is dropped, because
    this subprocess imports and executes modules an unattended agent wrote.
    """
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise MissingGradingEnvironment(
            f"the grading subprocess needs {', '.join(missing)} in the environment and "
            f"this process does not have it. Refusing to run: a verdict off a run that "
            f"could not start properly is not a verdict about the draft"
        )
    env = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _names_a_missing_environment_variable(raw: str) -> str | None:
    """The environment variable the child died on, or None when it did not.

    Both halves are required and that is the point: an upper-snake name inside a
    ``KeyError`` proves nothing on its own, since a generated transform indexing a
    record by an upper-case key raises exactly that. Paired with an ``os.environ`` /
    ``getenv`` access in the same output it is the allowlist, not the draft.
    """
    match = _ENV_KEY_ERROR.search(raw)
    if match is None:
        return None
    if not any(marker in raw for marker in _ENV_ACCESS_MARKERS):
        return None
    return match.group(1)


class NoTestPaths(ValueError):
    """Raised when :func:`run_pytest` is handed no paths at all.

    Not a not-ran outcome, because it is a caller bug rather than a fact about the
    draft — and a dangerous one. ``pytest`` with no path argument falls back to the
    ``testpaths`` setting in ``pyproject.toml``, so an empty list quietly means "collect
    and run this repository's entire suite" from inside a drafting loop.
    """


class UnusableBrief(UnmeasuredBrief):
    """Raised when a brief claims to be measured but carries no floors to measure against.

    The mirror of :meth:`casesignal.drafter.scaffold.Brief.__post_init__`'s own refusal,
    one layer down and for the layer's own reason. "Route the status through
    :func:`build_report`" is a necessary rule and not a sufficient one: ``brief=None``,
    ``brief={"floors": {}}``, and a brief whose floors block is a list or a string all
    satisfy the rule and buy nothing -- every one of them resolves ``PASS``, because a
    floors block that yields no names yields no vacuity either. A caller can obey the
    convention exactly and still get green over an unverified adapter.

    So the shape is refused where the brief actually arrives. ``inventory_measured: true``
    is a claim that the inventory pass ran and derived floors; a brief making that claim
    over a floors block this module cannot read is a brief whose flag is the only measured
    thing about it, and the flag is what everything downstream reads.

    Subclasses :class:`~casesignal.drafter.scaffold.UnmeasuredBrief` because it is the
    same condition at a different layer, so a caller already handling the generator's
    refusal handles this one too.
    """


class TransformNotDrafted(FileNotFoundError):
    """Raised when :func:`find_todos` is pointed at a ``transform.py`` that is not there.

    Returning ``[]`` for a missing file would be the module's own characteristic failure
    in miniature: "no TODOs found" and "nothing to find TODOs in" render identically in a
    report, and the second would read as the cleaner result. The parser pass writes both
    ``scrape.py`` and ``transform.py``; a run that reaches verification with no
    ``transform.py`` on disk produced no parser at all, and that is a louder finding than
    any TODO.

    Subclasses ``FileNotFoundError`` so a caller that already handles a missing file
    keeps working.
    """


@dataclass(frozen=True)
class TestOutcome:
    """One pytest invocation: did it run, and did it pass.

    ``passed`` and ``ran`` are separate because a run that never happened is not a run
    that failed. ``failures`` holds the short-summary lines verbatim so the loop's
    redactor can work on them; ``raw`` holds the whole of stdout and stderr, because the
    interesting part of a collection error is never in the summary.

    ``ran=False`` with ``passed=True`` is refused at construction. It is the exact shape
    of the bug this module exists to not have, and a dataclass that can hold it is a
    dataclass that will eventually be handed it.
    """

    passed: bool
    failures: list[str]
    raw: str
    ran: bool = True
    returncode: int | None = None

    def __post_init__(self) -> None:
        if self.passed and not self.ran:
            raise ValueError(
                "TestOutcome(passed=True, ran=False) is not a state: a run that did not "
                "happen cannot have passed. This is the 'non-zero exit read as success' "
                "defect made unrepresentable"
            )

    @property
    def verdict(self) -> str:
        """``"green"``, ``"red"`` or ``"not-run"`` — the three outcomes, named."""
        if not self.ran:
            return "not-run"
        return "green" if self.passed else "red"


@dataclass(frozen=True)
class Todo:
    """One marked ``TODO(field):`` the parser pass left behind.

    ``line`` is the 1-based physical line in the file as written. The generator's digest
    marker is always the file's LAST line, so it can never shift a number here; it is
    excluded from the scan anyway, so no Todo can ever be reported on it.
    """

    field: str
    line: int
    text: str


@dataclass(frozen=True)
class VerifyReport:
    """Everything one verification pass established.

    The first five fields are the contract the finishing task binds to. The rest are
    appended with defaults so that construction keeps working, and carry the inventory
    pass's advisories through to the PR body: ``vacuous_floors`` names the fields nothing
    can grade, ``unreachable_floors`` names the fields whose coverage test was predicted
    red before the parser was written, and ``advisories`` is the human-readable rendering
    of those two plus the two that bear on neither status nor verification.

    ``__post_init__`` refuses a ``status`` that contradicts ``vacuous_floors``, which is
    the same move :class:`TestOutcome` makes one level down and for the same reason. The
    dangerous assembly is not the uninformed one, it is the HALF-informed one: a caller
    who wants the vacuous fields in the PR body populates the field, resolves the status
    with the three-positional :func:`resolve_status` call the contract documents, and
    ships a report whose own ``summary()`` prints "1 field(s) no floor can grade" next to
    the word ``PASS``. That call is the more natural one to reach for -- it is the name
    the contract names -- so the pair has to be refused where it is held rather than
    trusted to be assembled correctly. :func:`build_report` never produces a refused
    pair.
    """

    status: VerifyStatus
    invariants: TestOutcome
    expectations: TestOutcome
    todos: list[Todo]
    coverage: Mapping[str, float]
    unreachable_floors: tuple[str, ...] = ()
    vacuous_floors: tuple[str, ...] = ()
    advisories: tuple[str, ...] = field(default_factory=tuple)
    live_probe: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.vacuous_floors:
            return
        required = [name for name in self.vacuous_floors if name in REQUIRED_FIELDS]
        if required and self.status is not VerifyStatus.FAIL:
            raise ValueError(
                f"VerifyReport({self.status.value}) carries vacuous floors on required "
                f"field(s) {required}: nothing in the generated suite asserts them, so "
                f"this is a FAIL. Resolve the status through build_report(brief=...), "
                f"which can see the brief; resolve_status cannot"
            )
        if self.status is VerifyStatus.PASS:
            raise ValueError(
                f"VerifyReport(PASS) carries vacuous floors {list(self.vacuous_floors)}: "
                f"a 0.0 floor renders no coverage test, so a plain PASS over these "
                f"fields is green over something nothing graded. The lowest honest "
                f"status here is PASS_WITH_TODOS -- see build_report(brief=...)"
            )

    @property
    def nothing_was_verified(self) -> bool:
        """True when neither generated module actually ran.

        The status is ``FAIL`` either way, but "every test failed" and "no test ran"
        call for opposite next moves, and a report that renders them the same forces an
        operator to open the raw output to tell which one happened.
        """
        return not self.invariants.ran and not self.expectations.ran

    def summary(self) -> str:
        """One line an operator can read without opening anything else."""
        head = (
            f"{self.status.value}: invariants {self.invariants.verdict}, "
            f"expectations {self.expectations.verdict}"
        )
        if self.nothing_was_verified:
            head += " — NOTHING WAS VERIFIED"
        if self.todos:
            head += f", {len(self.todos)} marked TODO(s)"
        if self.vacuous_floors:
            head += f", {len(self.vacuous_floors)} field(s) no floor can grade"
        return head


# --- running the generated tests ---


def run_pytest(
    paths: Sequence[Path],
    cwd: Path,
    *,
    timeout_s: float = 1800.0,
) -> TestOutcome:
    """Run the named test modules in a subprocess and classify the exit.

    ``subprocess.run`` is looked up on the module at call time rather than captured as a
    default argument, so the drafter test package's autouse spawn guard governs this the
    way it governs everything else in the package.

    Raises :class:`NoTestPaths` on an empty ``paths``; see that class for why an empty
    list is the one input that must not be interpreted charitably.
    """
    if not paths:
        raise NoTestPaths(
            "run_pytest was given no test paths. pytest with no path argument falls "
            "back to the `testpaths` setting, so this would collect and run the entire "
            "repository suite from inside a drafting loop"
        )

    command = [
        sys.executable,
        "-m",
        "pytest",
        *(str(path) for path in paths),
        "-q",
        "--no-header",
        # Guarantee the FAILED/ERROR short-summary lines this module parses, whatever
        # the ambient configuration would have chosen.
        "-rfE",
        # A drafting worktree is thrown away; leaving a .pytest_cache in it would make
        # `apply_back`'s allow-list argue with a directory nobody wrote on purpose.
        "-p",
        "no:cacheprovider",
        "-p",
        "casesignal.drafter.grading_plugin",
    ]
    env = _grading_environment()
    # The trusted plugin imports casesignal before pytest loads conftest. Select
    # the copied tree before interpreter startup, including for a live probe.
    if (cwd / "src").is_dir():
        env["PYTHONPATH"] = str((cwd / "src").resolve())

    results_xml = ""
    try:
        with tempfile.TemporaryDirectory(prefix="casesignal-grade-") as scratch:
            report_path = Path(scratch) / "results.xml"
            env.update(
                TMPDIR=scratch,
                HOME=scratch,
                PYTHONDONTWRITEBYTECODE="1",
                PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            )
            completed = subprocess.run(
                [*command, f"--junitxml={report_path}"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            if report_path.is_file():
                results_xml = report_path.read_text(encoding="utf-8")
    except subprocess.TimeoutExpired as expired:
        return TestOutcome(
            passed=False,
            failures=[f"pytest timed out after {timeout_s:g}s. Nothing was verified"],
            raw=_decode(expired.stdout) + _decode(expired.stderr),
            ran=False,
            returncode=None,
        )

    raw = completed.stdout + completed.stderr
    code = completed.returncode
    failures = _parse_failures(raw)

    if "grading isolation unavailable:" in raw:
        raise MissingGradingEnvironment(raw)
    if code == _EXIT_OK:
        try:
            cases = ET.fromstring(results_xml).findall(".//testcase")
        except ET.ParseError:
            cases = []
        if not cases or any(
            c.find("skipped") is not None
            or c.find("failure") is not None
            or c.find("error") is not None
            for c in cases
        ):
            return TestOutcome(
                passed=False,
                failures=["No complete passing test report; nothing was verified"],
                raw=raw,
                ran=False,
                returncode=code,
            )
        return TestOutcome(passed=True, failures=[], raw=raw, ran=True, returncode=code)

    missing = _names_a_missing_environment_variable(raw)
    if missing is not None:
        # Refused, not returned as a round. A round outcome here is fed back to a PAID
        # agent through `redact`, with a verdict naming the generated module as the
        # suspect -- so an operator's shell buys agent rounds to fix itself. This is the
        # one failure the environment allowlist can produce that the draft cannot, and
        # naming it is the whole reason the allowlist is safe to have.
        raise MissingGradingEnvironment(
            f"the grading subprocess failed on the environment variable {missing!r}, "
            f"which it does not carry. It runs on a fixed allowlist "
            f"(verify._INHERITED_ENV) rather than on the environment this process was "
            f"started in, so a name your shell has is not a name the draft has. This is "
            f"your environment, not the draft: nothing about the parser has been graded "
            f"and no round was scored against it. Either the generated code should not "
            f"read {missing!r}, or that name belongs on the allowlist -- adding it is a "
            f"deliberate edit next to the reasoning for every other entry"
        )

    if code == _EXIT_TESTS_FAILED:
        if not failures:
            return TestOutcome(
                passed=False,
                failures=[_NO_TEST_NAMED_AT_RC_1],
                raw=raw,
                ran=False,
                returncode=code,
            )
        return TestOutcome(passed=False, failures=failures, raw=raw, ran=True, returncode=code)

    reason = _NOT_RAN_REASONS.get(
        code, f"pytest exited {code}, which is not a documented outcome. Nothing was verified"
    )
    return TestOutcome(
        passed=False,
        failures=[reason, *failures],
        raw=raw,
        ran=False,
        returncode=code,
    )


def _decode(stream: Any) -> str:
    """``TimeoutExpired`` carries bytes or str or None depending on how it was raised."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return str(stream)


def _parse_failures(raw: str) -> list[str]:
    return [match.group(0).strip() for match in _FAILURE_LINE.finditer(raw)]


# --- classifying what the parser pass left behind ---


def find_todos(path: Path) -> list[Todo]:
    """Every marked ``TODO(field):`` in a drafted module, in file order.

    An unmarked ``TODO`` is ignored deliberately — see the module docstring. A missing
    file raises :class:`TransformNotDrafted` rather than returning an empty list.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as missing:
        raise TransformNotDrafted(
            f"{path} does not exist, so its TODOs were never read. An empty TODO list "
            f"here would read as a clean parser; a missing module means there is no "
            f"parser at all"
        ) from missing

    todos: list[Todo] = []
    for number, line in enumerate(_scannable_lines(text), start=1):
        # finditer, not search: two markers on one line are two claims, and `search`
        # silently kept only the first -- so `TODO(county): a  TODO(case_name): b`
        # reported the optional field and dropped the required one.
        matches = list(_TODO_MARKER.finditer(line))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            todos.append(
                Todo(
                    field=match.group("field").lower(),
                    line=number,
                    text=line[match.start() : end].strip(),
                )
            )
    return todos


def _scannable_lines(text: str) -> list[str]:
    """The file's lines with the generator's digest marker line dropped.

    The marker is the final line of every generated file and carries a session id, a
    timestamp and a sha256. It is not source the parser pass wrote, so it is not source
    this module reads: excluding it keeps it out of any line count derived from the scan
    and makes it impossible for a marker to be reported as a finding. Dropping the LAST
    line cannot shift any earlier line number, so ``Todo.line`` stays a true physical
    line of the file as written.
    """
    lines = text.splitlines()
    if lines and is_marker_line(lines[-1]):
        return lines[:-1]
    return lines


# --- the verdict ---


def resolve_status(
    invariants: TestOutcome,
    expectations: TestOutcome,
    todos: Sequence[Todo],
    *,
    vacuous_floors: Sequence[str] = (),
    unreachable_floors: Sequence[str] = (),
) -> VerifyStatus:
    """Resolve the tri-state.

    ``FAIL`` when either module went red, when either module did not run at all, when a
    required canonical field carries an unresolved marked TODO, or when a required
    canonical field's floor asserts nothing. ``PASS_WITH_TODOS`` when unresolved TODOs or
    ungradeable floors remain on other fields. ``PASS`` otherwise.

    ``unreachable_floors`` is accepted and deliberately not consulted; the module
    docstring gives the reasoning, and the parameter exists so that a caller passing it
    is answered by an explicit decision rather than by a ``TypeError``.

    **A caller holding a measured brief must go through** :func:`build_report`. This
    function cannot see the brief, so called with three positional arguments it cannot
    know a floor asserts nothing and will answer ``PASS`` over an ungradeable field.
    :meth:`VerifyReport.__post_init__` refuses the report that would result, but the
    refusal is a backstop; ``build_report`` is the route.
    """
    del unreachable_floors  # carried into the report, never into the verdict

    # Provably redundant today, and kept anyway: TestOutcome refuses passed=True with
    # ran=False, so ran=False implies passed=False and the next branch would catch it.
    # Deleting this line changes no behaviour -- it was run as a mutant and survived, as
    # an equivalent mutant should. It stays because the redundancy rests on an invariant
    # enforced in a DIFFERENT class, and "did not run is not a pass" is the whole point
    # of the module: it should be stated here rather than inferred from somewhere else.
    if not invariants.ran or not expectations.ran:
        return VerifyStatus.FAIL
    if not invariants.passed or not expectations.passed:
        return VerifyStatus.FAIL

    if any(todo.field in REQUIRED_FIELDS for todo in todos):
        return VerifyStatus.FAIL
    if any(name in REQUIRED_FIELDS for name in vacuous_floors):
        return VerifyStatus.FAIL

    if todos or vacuous_floors:
        return VerifyStatus.PASS_WITH_TODOS
    return VerifyStatus.PASS


def build_report(
    *,
    invariants: TestOutcome,
    expectations: TestOutcome,
    todos: Sequence[Todo],
    brief: Mapping[str, Any] | None,
) -> VerifyReport:
    """Assemble the report, consuming the measured brief's advisories.

    ``brief`` is the ``brief.json`` the inventory pass rewrote, and it has **no
    default**. That is the cheapest thing this module can do about the uninformed hole:
    it cannot make a wrong answer impossible, but it makes "I forgot the brief"
    unwriteable. A caller who has no brief must now say ``brief=None`` out loud, and
    silence -- which is what the hole actually is -- stops being expressible. The cost is
    four test call sites and nothing else; ``VerifyReport``'s field contract is untouched,
    because Task 14 binds to the dataclass's fields and not to this signature.

    ``brief=None`` is still accepted, and the reason is not "it would break existing
    callers" -- there are none yet, so that would be a claim about the future. It is that
    this module cannot tell "no brief exists for this run" from "the caller forgot", and
    inventing a refusal for silence would be a guess. The refusal fires only on a positive
    FALSE CLAIM: ``inventory_measured: true`` over floors that say nothing. Silence is
    unverified; a false claim is a lie, and only the second is refusable from here.

    ``coverage`` is taken from the coverage the floors were DERIVED from, not from the
    floors themselves: an operator reading "victim_age 0.92" wants what was observed, and
    a floor is that number minus a tolerance.

    The vacuous set is the UNION of the advisory key and what the floors themselves say,
    because the advisory is a sibling key and the floors are the measurement. A brief
    whose ``vacuous_floors`` key was dropped, re-keyed, or written as a string still
    carries ``{"case_name": 0.0}`` in its floors, and reading only the advisory would
    resolve that to ``PASS``. ``floor <= 0.0`` is exactly the vacuity condition and
    cannot false-positive: a STRUCTURED floor is measured coverage times 0.95 and a NARRATIVE floor is
    only ever zero when the measurement was at or below the tolerance.
    """
    measured: Mapping[str, Any] = brief or {}
    _refuse_a_brief_that_measured_nothing(measured)
    vacuous = tuple(
        sorted(set(_names(measured.get("vacuous_floors"))) | _floors_that_assert_nothing(measured))
    )
    unreachable = tuple(_names(measured.get("unreachable_floors")))
    status = resolve_status(
        invariants,
        expectations,
        todos,
        vacuous_floors=vacuous,
        unreachable_floors=unreachable,
    )
    return VerifyReport(
        status=status,
        invariants=invariants,
        expectations=expectations,
        todos=list(todos),
        coverage=_coverage_of(measured),
        unreachable_floors=unreachable,
        vacuous_floors=vacuous,
        advisories=_advisories(measured, vacuous, unreachable),
    )


def _refuse_a_brief_that_measured_nothing(brief: Mapping[str, Any]) -> None:
    """Refuse ``inventory_measured: true`` over a floors block that yields nothing.

    Only fires on the claim. A brief that never says it was measured is a partial or a
    caller-assembled one, and refusing those would break every legitimate call that hands
    this function what it happens to have.

    Note what this does NOT cover, deliberately: a floors block that is a usable mapping
    of entirely 0.0 floors passes here and is handled by the vacuity path instead, where
    every one of those fields lands in ``vacuous_floors`` and the status moves. The
    generator refuses that same brief outright one layer up.
    """
    if brief.get("inventory_measured") is not True:
        return
    floors = brief.get("floors")
    if isinstance(floors, Mapping) and floors:
        return
    raise UnusableBrief(
        f"brief says inventory_measured: true over a floors block this pass cannot read "
        f"({type(floors).__name__}"
        + (", empty" if isinstance(floors, Mapping) else "")
        + "). No floor means no vacuity and no coverage test, so the report would resolve "
        "PASS with nothing actually measured -- which is what the flag claims did happen. "
        "Re-run inventory.write_measured_brief"
    )


def _names(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(name) for name in raw]


def _floors_that_assert_nothing(brief: Mapping[str, Any]) -> set[str]:
    """Fields whose floor is at or below zero, read off the floors block itself.

    This is the half of the vacuity check that does not depend on a sibling key having
    survived intact. A floor of 0.0 is satisfied by a parser that extracts the field
    never, and the scaffold renders no coverage test for one at all.
    """
    raw = brief.get("floors")
    if not isinstance(raw, Mapping):
        return set()
    vacuous: set[str] = set()
    for name, floor in raw.items():
        # A boolean floor counts as vacuous rather than as unparseable. `_as_float`
        # excludes bool because `True` is a bad COVERAGE figure, and reusing that
        # judgment for floors fails in the green direction: JSON `false` reads far more
        # like 0.0 than like a type error, and a floor nobody can read is a floor that
        # grades nothing either way. Unreachable from an inventory-written brief; it is
        # the same shape as the advisory-key hole closed in the round before this one.
        if isinstance(floor, bool):
            vacuous.add(str(name))
            continue
        value = _as_float(floor)
        if value is not None and value <= 0.0:
            vacuous.add(str(name))
    return vacuous


def _as_float(value: Any) -> float | None:
    """A float, or None for anything that is not one. Never raises.

    A brief is written by an earlier pass and read here; a malformed entry in it should
    cost that entry, not the whole report. ``bool`` is excluded because ``True`` is a
    perfectly good float in Python and a perfectly bad coverage figure.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coverage_of(brief: Mapping[str, Any]) -> dict[str, float]:
    raw = brief.get("coverage")
    if not isinstance(raw, Mapping):
        return {}
    coverage: dict[str, float] = {}
    for name, entry in raw.items():
        if isinstance(entry, Mapping) and "coverage" in entry:
            value = _as_float(entry["coverage"])
        else:
            value = _as_float(entry)
        if value is not None:
            coverage[str(name)] = value
    return coverage


def _advisories(
    brief: Mapping[str, Any],
    vacuous: Sequence[str],
    unreachable: Sequence[str],
) -> tuple[str, ...]:
    lines: list[str] = []
    if vacuous:
        required = [name for name in vacuous if name in REQUIRED_FIELDS]
        lines.append(
            f"floors that assert nothing (no coverage test is rendered for a 0.0 floor, "
            f"so no parser can fail these): {', '.join(vacuous)}"
            + (f" — {', '.join(required)} are REQUIRED, hence FAIL" if required else "")
        )
    if unreachable:
        lines.append(
            f"floors above their own measurement (the rendered coverage test is expected "
            f"red from the first run; suspect the locator before the parser): "
            f"{', '.join(unreachable)}"
        )
    mispaged = _names(brief.get("suspected_page_mismatch"))
    if mispaged:
        lines.append(
            f"locators that scored markedly better on another page, so they are probably "
            f"filed under the wrong one: {', '.join(mispaged)}"
        )
    omission = brief.get("omission_rate")
    if isinstance(omission, (int, float)) and not isinstance(omission, bool) and omission > 0:
        omitted = _names(brief.get("omitted_fields"))
        lines.append(
            f"the reader pass omitted {omission:.0%} of the requested fields"
            + (f": {', '.join(omitted)}" if omitted else "")
        )
    return tuple(lines)


# --- the live probe's ceiling ---


class BudgetExceeded(RuntimeError):
    """Raised when budgeted code asks for one request more than it was allowed."""


class RequestBudget:
    """A ceiling on the requests budgeted code ASKS FOR, imposed below the code asking.

    Wraps any client exposing the request methods it knows about — in practice
    :class:`casesignal.etl.services.polite_http.PoliteHTTPClient` — counts every call and
    refuses past ``limit``. Every call is delegated untouched, so the SSRF allowlist, the
    IP-literal denylist, the DNS-rebinding guard and the per-redirect-hop revalidation
    all still run exactly as they do without the wrapper.

    *What the number counts, precisely.* One CALL, not one network send. Inside a single
    ``get`` the wrapped client may retry (``max_retries`` defaults to 4), may follow
    redirects, and fetches ``robots.txt`` once per host outside this counter entirely. So
    a limit of five bounds the crawl at five requested URLs and something on the order of
    twenty-five sends plus robots. The bound is real and it is what stops a runaway
    paginator; it is a constant factor looser than the raw send count, and a sentence
    that said "a hard ceiling on requests" would be describing a tighter guarantee than
    this gives.

    There is intentionally no ``__getattr__``: a wrapper that forwards unknown attributes
    would hand back the underlying client's own ``get`` and count nothing, which is a cap
    that exists right up until somebody reaches around it. The wrapped client is held
    under a name-mangled attribute for the same reason.
    """

    def __init__(self, client: Any, limit: int) -> None:
        if limit < 0:
            raise ValueError(f"a request budget cannot be negative: {limit}")
        self.__client = client
        self._limit = limit
        self._calls: list[tuple[str, str]] = []

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def spent(self) -> int:
        return len(self._calls)

    @property
    def remaining(self) -> int:
        return self._limit - self.spent

    @property
    def calls(self) -> tuple[tuple[str, str], ...]:
        """``(method, url)`` for every request that was ATTEMPTED, in order.

        Attempted, not completed: the charge is recorded before the delegate is called,
        so a request the client itself refuses -- a non-allowlisted host, a rebinding
        resolve -- is still counted. That is the correct direction (a refused request was
        still a request this code decided to make, and a paginator looping on refusals
        must still exhaust its budget), but it means this list is not a log of successes.
        """
        return tuple(self._calls)

    def get(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return self._spend("get", url, *args, **kwargs)

    def head(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return self._spend("head", url, *args, **kwargs)

    def post(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return self._spend("post", url, *args, **kwargs)

    def fetch_to_file(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return self._spend("fetch_to_file", url, *args, **kwargs)

    def close(self) -> None:
        closer = getattr(self.__client, "close", None)
        if closer is not None:
            closer()

    def __enter__(self) -> RequestBudget:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _spend(self, name: str, url: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self.__client, name, None)
        if method is None:
            raise AttributeError(
                f"the budgeted client has no {name!r}; RequestBudget wraps a client "
                f"rather than implementing one"
            )
        if self.spent >= self._limit:
            # Charged and refused BEFORE the delegate is called, so the request that
            # would have gone over the cap is never made. A counter incremented after a
            # successful call caps the count and not the traffic.
            raise BudgetExceeded(
                f"request budget of {self._limit} exhausted; refusing {name} {url!r}. "
                f"The cap lives below the adapter because pagination inside generated "
                f"code cannot be trusted to stop itself"
            )
        self._calls.append((name, url))
        return method(url, *args, **kwargs)
