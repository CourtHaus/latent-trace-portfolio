"""The finishing pass: bring the draft home, and tell a human the truth about it.

Everything upstream -- the census the capture pass refuses to fake, the floors the
inventory pass derives rather than accepts, the two-pass barrier that keeps the
parser from ever seeing the golden values -- exists so that one artefact is honest:
the pull request a person opens. A body that reads green over a draft nobody
verified spends all of it. A body that reads red without saying which red spends the
operator's afternoon instead.

So a red draft still ships. It ships as a pull request whose title names the failure,
whose body opens by saying a machine wrote it, and whose verdict section carries the
four-way classification the verify pass actually produced: passed, passed with marked
TODOs, went red, or never ran at all.

What never reaches the body
---------------------------
``verify.TestOutcome.failures`` and ``.raw`` are UNREDACTED. Redaction lives in
:func:`casesignal.drafter.loop.redact`, which the loop applies on the way into an
agent's prompt; the verify pass captures pytest's output verbatim because a
collection error is never legible in a summary line. A golden expectation failure's
assertion message therefore carries the transcribed source value, and a pull request
is a public artefact. This module renders counts, verdicts, and the loop's already
redacted round signatures. It never renders either field, and :func:`build_pr_body`
takes no path it could read one from.

What a signature means, and does not
------------------------------------
``RoundOutcome.signature`` is the redacted failure set for a round that ran tests,
EXCEPT for the four values in :data:`casesignal.drafter.loop.RESERVED_SIGNATURES`,
which name a condition under which no test ran at all. And a round that ran, went
red, and whose output parsed to zero failure lines carries the empty signature -- the
same value a green round carries. So :func:`round_reason` reads ``passed`` first, the
reserved names second, and treats an empty signature on a failed round as its own
third thing rather than as silence.

Which branch this pass writes to
--------------------------------
The destination is pinned by the claim's lease. The operator checkout must still
be on that branch before apply-back and before the explicit push refspec. The
internal worktree branch is separate and never the push destination.

Recovery
--------
A successful finish removes the worktree and releases the lease. A failure after
apply-back retains both, records the failure, and permits retry without paying for
another draft. An existing PR is updated only if its open head and adapter marker
match this draft; an unrelated PR is refused.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from casesignal.drafter import lease, loop, scaffold, verify, workspace
from casesignal.scout import registry as scout_registry
from casesignal.scout.models import Status

LOGGER = logging.getLogger(__name__)

OUTCOME_FILE = "outcome.json"
PR_BODY_FILE = "pr-body.md"

# The prefix this module owns in a registry candidate's free-text notes, so a
# re-run replaces its own line rather than stacking a new one under every retry.
NOTE_PREFIX = "drafted:"

# Branch names a machine draft is never committed to, whatever the remote says. The
# remote's own default is added to these rather than replacing them: a repository
# whose default is `develop` still has a `main` nobody wants a drafted adapter landing
# on, and asking the remote can fail (no origin, no fetched refs, an offline run).
PROTECTED_BRANCH_FALLBACKS: tuple[str, ...] = ("main", "master")

# Two operator-facing ways to add to that set without a new dependency, a network
# round-trip or an auth scope: a repository-local git config key, and an environment
# variable for a one-off run. A true permission check through the forge's API is
# deliberately NOT attempted -- it needs a token with a scope non-admins do not have,
# so it would fail ambiguously in exactly the situation it exists for.
# Every pre-flight refusal ends with this, because all three of them leave the lease
# HELD on purpose -- the draft is still live in its worktree and the lease is what stops
# a second run drafting over it. That is a deliberate departure from "the lease is
# released in a finally", so the escape hatch is named rather than left to be inferred.
#
# The escape hatch is a file to delete, and not `--force`, because `--force` does not
# work from here and never did. `finish`'s subparser has only the adapter positional;
# the flag lives on `claim` and on `run`. And routing an operator to `claim --force`
# would strand them too: `_claim` refuses a dirty checkout BEFORE it reaches
# `lease.acquire`, and by the time anyone is at `finish` the checkout is dirty with the
# scaffold's own output. Deleting the lease file is the one remedy that works, and it is
# pinned by test_deleting_the_lease_file_is_a_remedy_that_actually_works.
PREFLIGHT_UNTOUCHED = (
    "NOTHING HAS BEEN TOUCHED: the worktree still holds the draft and the lease is "
    "still HELD, so re-running finish costs nothing and re-drafts nothing. If you are "
    "abandoning this draft instead, delete data/drafts/<adapter>/lease.json -- finish "
    "has no --force, and claim --force cannot free it either, because claim refuses a "
    "dirty checkout before it ever reaches the lease and by now the scaffold's own "
    "output has made yours dirty."
)

PROTECTED_BRANCH_CONFIG_KEY = "casesignal.drafter.protected"
PROTECTED_BRANCH_ENV = "CASESIGNAL_DRAFTER_PROTECTED_BRANCHES"

Runner = Callable[..., Any]

# Captured at import so :func:`finish` can tell "the caller passed nothing" from
# "the caller passed a runner that happens to be subprocess.run". The signature
# still reads ``runner=subprocess.run``, which is the published contract; the
# identity check lets the default be RE-RESOLVED through the module at call time,
# so the drafter test package's autouse spawn guard governs a defaulted call the
# way it governs everything else. A default captured at definition time would be
# the original function object and would walk straight past that guard.
_DEFAULT_RUNNER: Runner = subprocess.run


class FinishRefusal(RuntimeError):
    """Raised for a finish this module will not carry out."""


class NothingDrafted(FinishRefusal):
    """Raised when there is nothing at all to commit.

    Not the same as a red draft, which ships. This is a run whose parser pass wrote
    nothing the allowlist admits AND whose scaffold output is already committed or
    absent: there is no change to open a pull request over, and an empty pull request
    is a worse artefact than a refusal.
    """


class UnusableBriefForFinish(FinishRefusal):
    """Raised in pre-flight when the brief does not name the adapter being finished.

    Every path here is keyed on the adapter name: the allowlist ``apply_back`` refuses
    against, the scaffold outputs that may be staged, the pull request title. A brief
    without one used to surface as a ``KeyError`` from inside the try block, which
    :func:`refusal_stage` reported as stage ``"unknown"``. Refused by name, in
    pre-flight, before the worktree or the checkout is touched.
    """


class PreflightFailed(FinishRefusal):
    """Raised when a pre-flight query itself failed, so the checkout could not be judged.

    ``git rev-parse --abbrev-ref HEAD`` failing is not a verdict about the branch; it is
    the absence of one. finish will not commit without knowing which branch it would be
    committing to, so this refuses -- and it refuses in pre-flight, where nothing has
    been touched, rather than being reported as a ``finish``-stage failure that would
    send the operator looking for a half-finished run.
    """


class ProtectedBranch(FinishRefusal):
    """Raised when the checkout is standing somewhere a machine draft must not land.

    ``workspace.create`` checks the draft's branch out IN THE WORKTREE. ``repo_root``'s
    own HEAD never moves, and ``apply_back`` copies into ``repo_root`` -- so the branch
    this pass commits and pushes is whichever one the OPERATOR happens to be standing
    on, not ``ws.branch``. Run from ``main``, an unguarded finish commits a machine
    draft to local ``main`` and pushes it to ``origin/main``.

    Task 15's CLI is a good second layer, but a module whose whole subject is state a
    failed run leaves behind must not be one ``cd`` away from writing to the default
    branch, and must not ship the guard as prose in a report. Everything the check
    needs -- ``runner`` and ``repo_root`` -- is already held here.
    """


class CommandFailed(FinishRefusal):
    """Raised when one of the git or ``gh`` invocations exits non-zero."""

    def __init__(self, cmd: Sequence[str], returncode: int, stderr: str) -> None:
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"`{' '.join(self.cmd)}` exited {returncode}: {stderr.strip()}")


# Which pass a refusal came out of, most-derived exception FIRST.
#
# ``verify.UnusableBrief`` subclasses ``scaffold.UnmeasuredBrief`` subclasses
# ``scaffold.ScaffoldRefusal`` subclasses ``ValueError``. The subclassing is
# deliberate -- it is the same condition at two layers, so one handler covers both --
# but it means an orchestrator that tests ``ScaffoldRefusal`` first attributes a
# VERIFY-stage refusal to the scaffold pass and sends the operator to re-run the
# wrong thing. Order is the whole content of this table.
_REFUSAL_STAGES: tuple[tuple[type[BaseException], str], ...] = (
    (verify.UnusableBrief, "verify"),
    (scaffold.UnmeasuredBrief, "inventory"),
    (scaffold.ScaffoldRefusal, "scaffold"),
    (verify.NoTestPaths, "verify"),
    (verify.TransformNotDrafted, "verify"),
    (loop.BarrierViolation, "draft"),
    (loop.LoopRefusal, "draft"),
    (workspace.DisallowedWrite, "apply-back"),
    (workspace.WorkspaceExists, "workspace"),
    (lease.LeaseHeld, "claim"),
    # Both refuse before anything is touched, so an orchestrator that reads them as
    # "finish" sends the operator to re-run the one stage that cannot help. They are
    # their own thing: fix the call or the checkout, then run finish again.
    (ProtectedBranch, "pre-flight"),
    (UnusableBriefForFinish, "pre-flight"),
    (PreflightFailed, "pre-flight"),
    (FinishRefusal, "finish"),
)


def refusal_stage(exc: BaseException) -> str:
    """Name the pass a refusal came out of, or ``"unknown"``.

    Exposed rather than kept private because the orchestrator has to attribute a
    refusal to a stage in order to tell the operator what to re-run, and the one
    ordering that gets it right is not the one an ``except`` chain written in
    declaration order produces. See :data:`_REFUSAL_STAGES`.
    """
    for kind, stage in _REFUSAL_STAGES:
        if isinstance(exc, kind):
            return stage
    return "unknown"


# --- the title and the body ---


def build_pr_title(adapter_name: str, status: verify.VerifyStatus) -> str:
    """The one line a reviewer sees in a list of pull requests.

    The status is in the title because a red draft ships anyway: the failure has to
    be visible before anything is opened. The title cannot carry more than that --
    it is handed only the status -- so the difference between "every test went red"
    and "no test ran" is the body's job, and :meth:`verify.VerifyReport.summary`
    renders it there.
    """
    return f"feat(adapter): draft {adapter_name} [VERIFY {status.value}]"


def round_reason(outcome: loop.RoundOutcome) -> str:
    """Why one drafting round ended, in a phrase.

    Three readings of ``signature``, tested in this order, because two of them are
    invisible to a consumer that reads the signature alone:

    * ``passed`` first, because a green round's signature is the empty string;
    * :data:`loop.RESERVED_SIGNATURES` second, because those four name a CONDITION
      (a stray write, a deletion, an unsupported entry, no change at all) under
      which no test ran, and rendering one as a failure set says a test went red
      when none was executed;
    * an empty signature on a failed round third, because it is genuinely ambiguous
      -- the round's output parsed to no failure lines -- and saying so is more
      honest than printing nothing next to the word "red".
    """
    if outcome.passed:
        return "green"
    if outcome.signature in loop.RESERVED_SIGNATURES:
        return f"no test ran ({outcome.signature})"
    if not outcome.signature:
        return "red, and the output parsed to no failure lines"
    return outcome.signature


def build_pr_body(
    brief: Mapping[str, Any],
    loop_report: loop.LoopReport,
    verify_report: verify.VerifyReport,
) -> str:
    """Everything a reviewer needs, and nothing that would leak a golden value.

    Reads only the three arguments. It is handed no repository root and no artifact
    directory on purpose: a function that cannot open a file cannot paste one into a
    public artefact, and the two fields that must never be pasted
    (``TestOutcome.failures`` and ``.raw``) are reachable from the report it does
    hold, so the restraint is written out below rather than assumed.
    """
    adapter_name = str(brief.get("adapter_name") or "(unnamed)")
    lines: list[str] = [
        f"## {adapter_name}",
        "",
        "This is a **machine draft**. An agent wrote the parser, a generator wrote "
        "the tests around it, and the only thing that has read either is a test run "
        "over captured fixtures. Nothing here has touched the live source. Review it "
        "as a proposal, not as a change that has already been checked.",
        "",
    ]
    lines += _verdict_section(verify_report)
    lines += _judgment_section(verify_report)
    lines += _loop_section(loop_report)
    lines += _todo_section(verify_report)
    lines += _coverage_section(verify_report)
    lines += _provenance_section(brief)
    return "\n".join(lines).rstrip() + "\n"


def _verdict_section(report: verify.VerifyReport) -> list[str]:
    lines = [
        "### Verify",
        "",
        report.summary(),
        "",
        "Scope: offline traversal, parser output, canonical mapping and stage wiring. "
        "Database persistence and production ingestion still require review.",
        "",
    ]
    if report.live_probe:
        lines += ["Live probe (advisory):", *[f"- {line}" for line in report.live_probe], ""]
    if report.nothing_was_verified:
        lines += [
            "> **NOTHING WAS VERIFIED.** Neither generated module ran, so nothing "
            "failed and nothing passed. This is not the same failure as a red suite "
            "and it does not have the same fix: look for a module that will not "
            "import or a collection that found no tests.",
            "",
        ]
    lines += [
        f"- invariants: {_outcome_line(report.invariants)}",
        f"- expectations: {_outcome_line(report.expectations)}",
        "",
        "Failure text is deliberately not reproduced here. A golden expectation "
        "assertion carries the value transcribed off the source, and this body is a "
        "public artefact, so only counts and the loop's redacted node ids appear. "
        "The full output is in the run artifacts on the operator's machine.",
        "",
    ]
    return lines


def _outcome_line(outcome: verify.TestOutcome) -> str:
    parts = [outcome.verdict]
    if outcome.returncode is not None:
        parts.append(f"pytest exit {outcome.returncode}")
    parts.append(f"{len(outcome.failures)} reported failure(s)")
    return ", ".join(parts)


def _judgment_section(report: verify.VerifyReport) -> list[str]:
    lines = [
        "### What a human still has to decide",
        "",
        "- Whether each field was read off the RIGHT part of the record. The locators "
        "and the golden values came from the same reader round, so a field "
        "misidentified there is green here and wrong everywhere downstream. Only the "
        "source itself settles that.",
        "- Whether the source is in scope and the catalog entry describes it correctly.",
        "- Whether the generated tests assert the things worth asserting.",
        "",
    ]
    if report.vacuous_floors:
        lines += [
            f"- **{len(report.vacuous_floors)} field(s) no floor can grade**: "
            f"{', '.join(report.vacuous_floors)}. A 0.0 floor renders no coverage "
            f"test, so nothing in the suite asserts these.",
            "",
        ]
    if report.unreachable_floors:
        lines += [
            f"- **{len(report.unreachable_floors)} floor(s) predicted unreachable**: "
            f"{', '.join(report.unreachable_floors)}. The inventory pass measured "
            f"coverage below the floor before a parser existed.",
            "",
        ]
    if report.advisories:
        lines += ["Advisories carried through from the inventory pass:", ""]
        lines += [f"- {line}" for line in report.advisories]
        lines += [""]
    return lines


def _loop_section(report: loop.LoopReport) -> list[str]:
    count = len(report.rounds)
    lines = [
        "### The drafting loop",
        "",
        f"{count} round{'' if count == 1 else 's'}, "
        f"final verdict {'green' if report.passed else 'not green'}, "
        f"stopped because: {report.stopped_because}",
        "",
    ]
    for outcome in report.rounds:
        timed_out = " (timed out)" if outcome.timed_out else ""
        lines.append(f"- round {outcome.index}: {round_reason(outcome)}{timed_out}")
    lines.append("")
    return lines


def _todo_section(report: verify.VerifyReport) -> list[str]:
    if not report.todos:
        return ["### Marked TODOs", "", "None.", ""]
    lines = [
        "### Marked TODOs",
        "",
        "Each one is a field the parser pass declined to finish. They are in the "
        "drafted source, not in this body's accounting of it.",
        "",
    ]
    for todo in report.todos:
        lines.append(f"- line {todo.line}: {todo.text}")
    lines.append("")
    return lines


def _coverage_section(report: verify.VerifyReport) -> list[str]:
    if not report.coverage:
        return []
    lines = [
        "### Locator coverage, measured by the inventory pass",
        "",
        "This is what the READER's locators found in the captured records, measured "
        "before any parser existed. It describes the source and the locators. It is "
        "NOT a measurement of the drafted parser and must not be read as one; it is "
        "here because it is the floor each generated coverage test was derived from.",
        "",
    ]
    for name in sorted(report.coverage):
        lines.append(f"- {name}: {report.coverage[name]:.2f}")
    lines.append("")
    return lines


def _provenance_section(brief: Mapping[str, Any]) -> list[str]:
    lines = [
        "### Draft provenance",
        "",
        f"- adapter: {brief.get('adapter_name') or '(unnamed)'}",
        f"- capture session: {brief.get('session_id') or '(unrecorded)'}",
        f"- candidate: {brief.get('candidate_id') or '(unrecorded)'}",
    ]
    if brief.get("records_captured") is not None:
        lines.append(f"- records captured: {brief.get('records_captured')}")
    if brief.get("index_url"):
        lines.append(f"- index url: {brief.get('index_url')}")
    lines.append("")
    return lines


# --- what may be committed ---


def adapter_name_of(brief: Mapping[str, Any]) -> str:
    """The brief's adapter name, read the one way every reader in this module reads it."""
    return str(brief.get("adapter_name") or "")


def parser_allowed_paths(brief: Mapping[str, Any]) -> list[str]:
    """The parser pass's own prefix, via ``loop`` but through this module's brief reading.

    ``loop.default_allowed_paths`` subscripts ``brief['adapter_name']``. Calling it with
    a raw brief put a bare ``KeyError`` inside :func:`finish`'s try block, which
    :func:`refusal_stage` then attributed to ``"unknown"`` -- a caller's malformed brief
    reported as an unattributable failure of the drafting pipeline. The name is resolved
    here first, and a brief that has none is refused by name in pre-flight.
    """
    return loop.default_allowed_paths({**brief, "adapter_name": adapter_name_of(brief)})


def draft_owned_paths(brief: Mapping[str, Any]) -> list[str]:
    """Every repo path this pipeline is allowed to have written, for this adapter.

    The parser pass's own package comes from
    :func:`loop.default_allowed_paths`, so the containment boundary is stated once.
    The rest are the scaffold pass's outputs, which it wrote straight into the
    operator's checkout rather than into the worktree, and which therefore never
    appear in ``apply_back``'s return value even though the pull request is
    incomplete without them.

    The list is a bound, not a wish: :func:`finish` stages the applied paths plus
    whatever in the checkout is dirty AND matches one of these. Nothing else is
    staged, so an operator's unrelated work in progress cannot be swept into a
    machine-drafted commit.
    """
    adapter_name = adapter_name_of(brief) or "(unnamed)"
    paths = [
        # Re-keyed rather than passed through, so the ONE place the parser's prefix is
        # spelled stays loop.default_allowed_paths while a brief missing the key is
        # read the way every other reader here reads it.
        *loop.default_allowed_paths({**brief, "adapter_name": adapter_name}),
        f"tests/unit/etl/adapters/test_{adapter_name}_invariants.py",
        f"tests/unit/etl/adapters/test_{adapter_name}_expectations.py",
        # Both generated modules resolve their fixtures as
        # ``tests/fixtures/<adapter>``, and the CLI copies the capture's fixtures
        # there so a drafting round has something to parse. Left out of this list
        # they are never staged, and the pull request carries two test modules that
        # fail on a missing file for every reviewer who runs them.
        f"tests/fixtures/{adapter_name}",
        f"docs/drafts/{adapter_name}.md",
        "src/casesignal/etl/runners/run_pipeline.py",
    ]
    state = str(brief.get("state") or "")
    if state:
        paths.append(f"src/casesignal/etl/sources/cold_case_{state.lower()}.yaml")
    return paths


def _dirty_draft_paths(
    repo_root: Path, brief: Mapping[str, Any], runner: Runner, warnings: list[str]
) -> list[str]:
    """The draft-owned paths that are dirty in the operator's checkout.

    Asked with a pathspec so git does the filtering, then filtered AGAIN through
    :func:`workspace.stray_writes` -- the same matcher ``apply_back`` refuses with,
    so "inside the boundary" cannot mean two things in one run. The second filter is
    what makes the crude porcelain parse below safe: any field it misreads simply
    fails to match and is dropped.

    A failure to ask is a warning and not a refusal. This is a completeness
    improvement on the commit, and losing it costs a reviewer a follow-up push; it
    must not cost the pull request.
    """
    owned = draft_owned_paths(brief)
    cmd = ["git", "status", "--porcelain", "-z", "--untracked-files=all", "--", *owned]
    try:
        proc = _run(runner, repo_root, cmd)
    except (FinishRefusal, OSError) as exc:
        warnings.append(f"could not list the checkout's draft paths: {exc}")
        return []
    found: list[str] = []
    for field in _text(getattr(proc, "stdout", "")).split("\0"):
        if len(field) <= 3:
            continue
        found.append(field[3:])
    return [path for path in found if not workspace.stray_writes([path], owned)]


# --- running the commands ---


def _attempt(runner: Runner, cwd: Path, cmd: Sequence[str]) -> Any:
    """Run a command and hand back its result unjudged.

    Split out so exactly ONE place knows how this module calls a runner. The probe in
    :func:`_commit` needs the result without the refusal, and when it spelled the
    keyword arguments out for itself there were two places that had to agree about the
    convention forever.
    """
    return runner(list(cmd), cwd=str(cwd), capture_output=True, text=True)


def _run(runner: Runner, cwd: Path, cmd: Sequence[str]) -> Any:
    proc = _attempt(runner, cwd, cmd)
    returncode = int(getattr(proc, "returncode", 0) or 0)
    if returncode != 0:
        raise CommandFailed(cmd, returncode, _text(getattr(proc, "stderr", "")))
    return proc


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def current_branch(repo_root: Path, runner: Runner) -> str:
    """The branch ``repo_root``'s checkout is standing on; ``"HEAD"`` when detached."""
    proc = _run(runner, repo_root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return _text(getattr(proc, "stdout", "")).strip()


def _remote_default_branch(repo_root: Path, runner: Runner) -> str:
    """The remote's default branch, or ``""`` when it cannot be resolved.

    ``git symbolic-ref --short refs/remotes/origin/HEAD`` answers ``origin/main``; the
    remote name is stripped. Failure is not a refusal -- a fresh clone that has never
    fetched, or a repository with no ``origin``, simply has no answer here, and
    :data:`PROTECTED_BRANCH_FALLBACKS` still covers the names that matter.
    """
    try:
        proc = _run(
            runner, repo_root, ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]
        )
    except (FinishRefusal, OSError):
        return ""
    ref = _text(getattr(proc, "stdout", "")).strip()
    return ref.split("/", 1)[1] if "/" in ref else ref


def protected_branches(repo_root: Path, runner: Runner) -> set[str]:
    """Every branch name this pass refuses to commit a machine draft onto.

    Four sources, unioned: the built-in fallbacks, the remote's own default, a
    repository-local git config key, and an environment variable. Union rather than
    override at every step -- a repository whose default is ``develop`` still has a
    ``main`` nobody wants a drafted adapter landing on.
    """
    names = set(PROTECTED_BRANCH_FALLBACKS)
    default = _remote_default_branch(repo_root, runner)
    if default:
        names.add(default)
    names.update(_configured_protected_branches(repo_root, runner))
    names.update(_split_names(os.environ.get(PROTECTED_BRANCH_ENV, "")))
    return {name for name in names if is_branch_name(name)}


# Characters git-check-ref-format forbids in a ref component, plus the ones that would
# make a name unusable here. A value that cannot be a branch is not a branch, and
# admitting one to the protected set would refuse a checkout for a name nothing can be
# standing on -- or, worse, quietly match a mangled value against a mangled answer.
_ILLEGAL_IN_BRANCH = frozenset(" \t\\~^:?*[")


def is_branch_name(name: str) -> bool:
    """Could git actually have a branch called this?

    Applied to everything that joins the protected set, because three of its four
    sources are free text: a git config value, an environment variable, and whatever
    ``git symbolic-ref`` answered. Filtering here keeps a malformed entry from silently
    becoming a rule.
    """
    if not name or name.startswith("/") or name.endswith("/") or name.endswith(".lock"):
        return False
    if name == "@" or ".." in name or "@{" in name:
        return False
    return not any(char in _ILLEGAL_IN_BRANCH for char in name)


def _configured_protected_branches(repo_root: Path, runner: Runner) -> list[str]:
    """``git config --get-all casesignal.drafter.protected``, or nothing.

    ``_attempt`` rather than ``_run``: ``git config --get-all`` exits 1 when the key is
    simply unset, which is the ordinary case and not a failure.
    """
    proc = _attempt(runner, repo_root, ["git", "config", "--get-all", PROTECTED_BRANCH_CONFIG_KEY])
    if int(getattr(proc, "returncode", 0) or 0) != 0:
        return []
    names: list[str] = []
    for line in _text(getattr(proc, "stdout", "")).splitlines():
        names.extend(_split_names(line))
    return names


def _split_names(raw: str) -> list[str]:
    """Comma- or whitespace-separated branch names."""
    return [part.strip() for part in raw.replace(",", " ").split() if part.strip()]


def _refuse_an_unusable_brief(brief: Mapping[str, Any]) -> None:
    """Refuse a brief this pass cannot key anything on."""
    if not adapter_name_of(brief):
        raise UnusableBriefForFinish(
            "the brief names no adapter_name. finish keys the apply-back allowlist, "
            "the stageable paths and the pull request title on it, so there is nothing "
            f"to finish. {PREFLIGHT_UNTOUCHED}"
        )


def _refuse_a_protected_branch(repo_root: Path, runner: Runner) -> str:
    """Return the branch to draft on, or refuse before anything has been touched.

    Called FIRST, ahead of ``apply_back``, so a refusal leaves the operator's checkout
    byte-for-byte as it was: no copied files, nothing staged, nothing committed.
    """
    try:
        branch = current_branch(repo_root, runner)
    except CommandFailed as exc:
        raise PreflightFailed(
            f"could not read the current branch of {repo_root} ({exc}). finish will not "
            f"commit without knowing which branch it would commit to. {PREFLIGHT_UNTOUCHED}"
        ) from exc
    if not branch or branch == "HEAD":
        raise ProtectedBranch(
            f"the checkout at {repo_root} is not on a named branch (git rev-parse "
            f"--abbrev-ref HEAD said {branch!r}). finish commits and pushes what it "
            f"applies back, and a detached HEAD is not somewhere that can go. Check "
            f"out a branch for this draft and re-run. {PREFLIGHT_UNTOUCHED}"
        )
    protected = protected_branches(repo_root, runner)
    # Case-folded on BOTH sides. A checkout on Windows or macOS is case-insensitive, so
    # `Main` and `MAIN` are the same branch there as `main` -- and this project runs
    # from WSL against Windows tooling, which is exactly that case.
    if branch.casefold() in {name.casefold() for name in protected}:
        raise ProtectedBranch(
            f"refusing to finish onto {branch!r}, which is a protected branch "
            f"({', '.join(sorted(protected))}). finish commits into the checkout at "
            f"{repo_root} and pushes it -- the draft's own worktree branch is a "
            f"different branch and is about to be destroyed -- so this would commit a "
            f"machine draft to {branch!r} and push it to the remote. Run "
            f"`git checkout -b draft/<adapter>` first. {PREFLIGHT_UNTOUCHED}"
        )
    return branch


def _commit(repo_root: Path, paths: Sequence[str], message: str, runner: Runner) -> bool:
    """Commit exactly ``paths``; return False when there was nothing to commit.

    ``git commit -- <paths>`` is ``--only`` mode: it commits those paths and nothing
    else, so an operator with unrelated work already in the index does not find it
    inside a machine-drafted commit.

    A non-zero exit is disambiguated by asking git, not by matching its prose:
    ``git diff --cached --quiet -- <paths>`` exits 0 when nothing is staged there,
    which is the benign "already committed" case a re-run hits, and 1 when something
    is. Matching on "nothing to commit" would be a locale-dependent guess.
    """
    try:
        _run(runner, repo_root, ["git", "commit", "-m", message, "--", *paths])
    except CommandFailed:
        probe = _attempt(runner, repo_root, ["git", "diff", "--cached", "--quiet", "--", *paths])
        if int(getattr(probe, "returncode", 0) or 0) == 0:
            return False
        raise
    return True


def _urls_in(stream: Any) -> list[str]:
    """The URL lines in a captured stream, in order.

    ``gh`` prints more than the URL: a release notice, a "to learn more" footer, an
    occasional warning. Taking the last non-empty line therefore returns prose often
    enough to matter, and that string would be written to ``outcome.json`` as the pull
    request URL and into the registry note as ``drafted: PR ! A new release of gh...``.
    Refusing to return ``""`` for an un-created pull request and then returning a
    sentence for one is the same defect one step along, so the shape is checked.
    """
    urls: list[str] = []
    for raw in _text(stream).splitlines():
        line = raw.strip()
        if not line.startswith("http"):
            continue
        # The URL TOKEN, not the whole line: `gh` appends status words often enough
        # ("https://.../pull/9 (created)") and returning the line verbatim would put
        # that suffix into outcome.json and the registry note. Whitespace-delimited,
        # which is what a URL on its own line is bounded by.
        urls.append(line.split()[0])
    return urls


def _pull_request_urls(stream: Any) -> list[str]:
    """The pull-request URLs in a captured stream.

    Two filters, because ``gh`` puts noise on BOTH sides of the answer. A release
    notice or a "to learn more" footer is not a URL at all, which the first filter
    settles. But a trailing ``See https://cli.github.com/manual`` IS a URL, and taking
    the last one would return the manual -- the same defect as returning prose, one
    step along again. So the shape is checked all the way down to ``/pull/`` rather
    than trusting a position in the output.
    """
    found: list[str] = []
    for url in _urls_in(stream):
        # De-duplicated before anything counts them, so `gh` echoing the same URL twice
        # is not read as two different pull requests and refused as ambiguous.
        if "/pull/" in url and url not in found:
            found.append(url)
    return found


def _open_pull_request(
    repo_root: Path, title: str, body_path: Path, runner: Runner, warnings: list[str]
) -> str:
    """Create the pull request and return its URL, or adopt the one already there.

    The body goes in through ``--body-file`` rather than ``--body``: it is long, it is
    multi-line, and it is the artefact the operator can re-read on disk afterwards to
    see exactly what was published.

    A branch that already has a pull request makes ``gh pr create`` exit non-zero, and
    that is the ordinary shape of a re-run: the registry write failed, the operator
    ran finish again, the commit was benign and the push a no-op, and the only thing
    left is a pull request that already exists. :func:`_commit` goes to real trouble to
    make that case benign; this asks ``gh pr view`` for the same reason. If THAT also
    fails, the original failure is the honest one and is re-raised.
    """
    try:
        proc = _run(
            runner,
            repo_root,
            ["gh", "pr", "create", "--title", title, "--body-file", str(body_path)],
        )
    except CommandFailed as create_error:
        try:
            proc = _run(
                runner, repo_root, ["gh", "pr", "view", "--json", "url,headRefName,body,state"]
            )
        except CommandFailed:
            raise create_error from None
        try:
            info = json.loads(proc.stdout)
        except (ValueError, TypeError):
            raise create_error from None
        if not isinstance(info, dict):
            raise create_error from None
        marker = body_path.read_text(encoding="utf-8").splitlines()[0]
        if (
            info.get("headRefName") != current_branch(repo_root, runner)
            or info.get("state") != "OPEN"
            or not marker.startswith("<!-- casesignal-adapter:")
            or marker not in str(info.get("body", ""))
        ):
            raise FinishRefusal(
                "existing pull request does not belong to this adapter; draft retained"
            ) from None
        existing = str(info.get("url", ""))
        if _pull_request_urls(existing) != [existing]:
            raise FinishRefusal("existing pull request has no valid URL; draft retained") from None
        _run(
            runner,
            repo_root,
            ["gh", "pr", "edit", existing, "--title", title, "--body-file", str(body_path)],
        )
        warnings.append(f"updated the existing adapter pull request at {existing}")
        return existing
    urls = _pull_request_urls(getattr(proc, "stdout", ""))
    if len(urls) != 1:
        raise FinishRefusal(
            f"`gh pr create` exited 0 but printed {len(urls)} pull request URL(s) "
            f"{urls}; exactly one was expected. The pull request may or may not "
            f"exist, and guessing which URL is it would put the wrong link in the "
            f"registry and the outcome record. Check the branch on the remote before "
            f"re-running finish"
        )
    return urls[0]


def _existing_pull_request(repo_root: Path, runner: Runner) -> str:
    """The URL of the pull request already open for this branch, or ``""``."""
    try:
        proc = _run(runner, repo_root, ["gh", "pr", "view", "--json", "url", "--jq", ".url"])
    except (FinishRefusal, OSError):
        return ""
    urls = _pull_request_urls(getattr(proc, "stdout", ""))
    return urls[0] if len(urls) == 1 else ""


# --- the registry transition ---


def _record_in_registry(
    registry_path: Path,
    brief: Mapping[str, Any],
    pr_url: str,
    report: verify.VerifyReport,
) -> str:
    """Move an accepted candidate to ``needs_review``, and say what happened.

    NOT through :meth:`scout_registry.Registry.upsert`. That method enforces a
    no-regression rule over a lifecycle order in which ``accepted`` sits ABOVE
    ``needs_review``, so an upsert of a needs-review candidate over an accepted one
    silently restores ``accepted`` and the transition this function exists to make
    never happens. The candidate is mutated in place and saved instead.

    ``ingested`` is left alone: it is a human's statement that the adapter is in
    production, and a re-drafted candidate does not retract it.

    The registry file is gitignored and local to one machine, so this is operator
    bookkeeping. Nothing about the pull request depends on it, which is why every
    outcome here is a returned sentence rather than an exception.
    """
    candidate_id = str(brief.get("candidate_id") or "")
    if not candidate_id:
        return "skipped: the brief carries no candidate_id"
    if not registry_path.exists():
        return f"skipped: no registry at {registry_path}"
    registry = scout_registry.Registry.load(registry_path)
    candidate = registry.get(candidate_id)
    if candidate is None:
        return f"skipped: {candidate_id} is not in the registry"
    if candidate.status is Status.INGESTED:
        return f"left {candidate_id} at ingested, which only a human retracts"
    if candidate.status not in (Status.ACCEPTED, Status.NEEDS_REVIEW):
        return (
            f"left {candidate_id} at {candidate.status.value}: only an accepted "
            f"candidate moves to needs_review"
        )
    previous = candidate.status.value
    candidate.status = Status.NEEDS_REVIEW
    candidate.notes = _annotated(
        candidate.notes, f"{NOTE_PREFIX} PR {pr_url or '(none)'}, verify {report.status.value}"
    )
    registry.save(registry_path)
    return f"{candidate_id}: {previous} -> needs_review"


def _annotated(notes: str | None, line: str) -> str:
    """Replace this module's own note line, keeping anyone else's."""
    kept = [
        existing for existing in (notes or "").splitlines() if not existing.startswith(NOTE_PREFIX)
    ]
    return "\n".join([*kept, line]).strip()


# --- the outcome record ---


def _outcome_record(
    *,
    ws: workspace.Workspace,
    brief: Mapping[str, Any],
    loop_report: loop.LoopReport,
    verify_report: verify.VerifyReport,
    applied: Sequence[str],
    worktree_kept: bool,
    staged: Sequence[str],
    pr_url: str,
    committed_to: str,
    pushed: bool,
    registry_note: str,
    warnings: Sequence[str],
    error: BaseException | None,
) -> dict[str, Any]:
    """What this run did, in the shape an operator or a later run can read back.

    Carries counts where the verify report carries text, for the same reason the
    pull request body does: one rule about the unredacted fields is easier to keep
    than two, and an outcome record is the file an operator is most likely to paste
    somewhere when asking for help.

    Two different residues are named, because they are left behind by different
    failures and cleared by different commands.

    ``branch`` is the DRAFT's worktree branch, which ``workspace.destroy`` keeps on
    purpose; ``workspace.create`` refuses a second draft under the same name until
    someone deletes it, so the name has to be written where that someone will look.

    ``committed_to`` is the OPERATOR's branch -- the one this pass actually commits
    into, which is whatever ``repo_root`` was standing on and is never ``branch``. It
    is empty until the commit succeeds. When ``gh pr create`` fails after the commit
    and the push, THAT branch carries a machine-drafted commit already on the remote,
    and calling ``branch`` "the only residue" would have sent the operator to clean up
    the wrong thing entirely. ``pushed`` says whether it reached the remote.
    """
    record: dict[str, Any] = {
        "adapter_name": brief.get("adapter_name"),
        "candidate_id": brief.get("candidate_id"),
        "session_id": brief.get("session_id"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pr_url": pr_url,
        "branch": ws.branch,
        "worktree": str(ws.path),
        "committed_to": committed_to,
        "pushed": pushed,
        "worktree_kept": worktree_kept,
        "verify": {
            "status": verify_report.status.value,
            "summary": verify_report.summary(),
            "nothing_was_verified": verify_report.nothing_was_verified,
            "invariants": _outcome_json(verify_report.invariants),
            "expectations": _outcome_json(verify_report.expectations),
            "todos": [
                {"field": todo.field, "line": todo.line, "text": todo.text}
                for todo in verify_report.todos
            ],
            "locator_coverage": dict(verify_report.coverage),
            "unreachable_floors": list(verify_report.unreachable_floors),
            "vacuous_floors": list(verify_report.vacuous_floors),
            "advisories": list(verify_report.advisories),
            "live_probe": list(verify_report.live_probe),
        },
        "loop": {
            "passed": loop_report.passed,
            "stopped_because": loop_report.stopped_because,
            "rounds": [
                {
                    "index": outcome.index,
                    "passed": outcome.passed,
                    "signature": outcome.signature,
                    "reason": round_reason(outcome),
                    "timed_out": outcome.timed_out,
                }
                for outcome in loop_report.rounds
            ],
        },
        "applied_paths": list(applied),
        "staged_paths": list(staged),
        "registry": registry_note,
        "warnings": list(warnings),
    }
    if error is not None:
        record["error"] = {
            "stage": refusal_stage(error),
            "type": type(error).__name__,
            "message": str(error),
        }
    return record


def _outcome_json(outcome: verify.TestOutcome) -> dict[str, Any]:
    """Counts and verdicts only; never ``failures`` and never ``raw``."""
    return {
        "verdict": outcome.verdict,
        "ran": outcome.ran,
        "passed": outcome.passed,
        "returncode": outcome.returncode,
        "failure_count": len(outcome.failures),
    }


def _write_outcome(draft_dir: Path, record: Mapping[str, Any]) -> None:
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / OUTCOME_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)  # atomic: never leaves a half-written outcome behind


# --- the pass itself ---


def finish(
    *,
    ws: workspace.Workspace,
    brief: Mapping[str, Any],
    loop_report: loop.LoopReport,
    verify_report: verify.VerifyReport,
    draft_dir: Path,
    registry_path: Path,
    runner: Runner = subprocess.run,
) -> str:
    """Apply the draft back, commit it, open a pull request, and clean up.

    Returns the pull request URL. Raises on anything that stopped it from being
    created -- but only AFTER the worktree has been destroyed, the outcome record
    written, and the lease released, because those three are what a later run needs
    in order to be possible at all.
    """
    if runner is _DEFAULT_RUNNER:
        # Re-resolved through the module rather than used as captured, so a test
        # that patches subprocess.run -- including the package's autouse spawn
        # guard -- governs a defaulted call. See _DEFAULT_RUNNER.
        runner = subprocess.run

    adapter_name = str(brief.get("adapter_name") or "")
    repo_root = ws.repo_root
    warnings: list[str] = []
    applied: list[str] = []
    staged: list[str] = []
    pr_url = ""
    applied_back = False
    committed_to = ""
    pushed = False
    registry_note = "not attempted"
    error: BaseException | None = None

    # PRE-FLIGHT, and deliberately OUTSIDE the try below. Everything in that try is
    # covered by a finally that destroys the worktree, and the worktree holds the ONLY
    # copy of the drafted adapter -- nothing ever commits inside it, and destroy is
    # `git worktree remove --force`. A refusal raised from inside the try would
    # therefore force-delete the whole agent-written draft on exactly the scenario the
    # branch guard exists for, leaving a branch byte-identical to main and a bill for a
    # re-drafted agent session on a self-funded project. Refusing out here touches
    # nothing: the worktree stands, the lease stays held, and re-running finish after
    # `git checkout -b` costs nothing.
    _refuse_an_unusable_brief(brief)
    branch_here = _refuse_a_protected_branch(repo_root, runner)
    claimed = lease.read(draft_dir)
    if claimed is None or claimed.branch != branch_here:
        raise PreflightFailed(
            f"finish requires the claimed destination branch; claimed "
            f"{claimed.branch if claimed else None!r}, current {branch_here!r}. "
            "Switch back to the claimed branch before finishing."
        )

    try:
        applied = workspace.apply_back(ws, parser_allowed_paths(brief))
        # Set the instant apply_back RETURNS, so a completed survey that found nothing
        # is never confused with a refusal that left the changes in the worktree.
        applied_back = True
        staged = _staged_paths(repo_root, applied, brief, runner, warnings)
        if not staged:
            raise NothingDrafted(
                f"nothing to commit for {adapter_name or 'this draft'}: the parser "
                f"pass wrote nothing the allowlist admits and no scaffold output is "
                f"uncommitted. There is no change to open a pull request over"
            )
        _run(runner, repo_root, ["git", "add", "--", *staged])

        title = build_pr_title(adapter_name, verify_report.status)
        body = f"<!-- casesignal-adapter:{adapter_name} -->\n" + build_pr_body(
            brief, loop_report, verify_report
        )
        draft_dir.mkdir(parents=True, exist_ok=True)
        body_path = draft_dir / PR_BODY_FILE
        body_path.write_text(body, encoding="utf-8")

        if not _commit(repo_root, staged, _commit_message(title, brief), runner):
            warnings.append("nothing was staged to commit; the paths were already committed")
        committed_to = branch_here
        if current_branch(repo_root, runner) != claimed.branch:
            raise PreflightFailed("destination branch changed before publication; draft retained")
        _run(
            runner,
            repo_root,
            ["git", "push", "--set-upstream", "origin", f"HEAD:refs/heads/{claimed.branch}"],
        )
        pushed = True
        pr_url = _open_pull_request(repo_root, title, body_path, runner, warnings)
        registry_note = _registry_note(registry_path, brief, pr_url, verify_report, warnings)
    except BaseException as exc:  # noqa: B036 -- re-raised below; the finally is the point
        error = exc
        raise
    finally:
        _cleanup(
            ws=ws,
            brief=brief,
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            applied=applied,
            applied_back=applied_back,
            staged=staged,
            pr_url=pr_url,
            committed_to=committed_to,
            pushed=pushed,
            registry_note=registry_note,
            warnings=warnings,
            error=error,
        )
    return pr_url


def _staged_paths(
    repo_root: Path,
    applied: Sequence[str],
    brief: Mapping[str, Any],
    runner: Runner,
    warnings: list[str],
) -> list[str]:
    """The applied paths plus the scaffold's own uncommitted output, deduplicated."""
    paths = list(applied)
    seen = set(paths)
    for path in _dirty_draft_paths(repo_root, brief, runner, warnings):
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return sorted(paths)


def _commit_message(title: str, brief: Mapping[str, Any]) -> str:
    session = brief.get("session_id") or "(unrecorded)"
    return (
        f"{title}\n\n"
        f"Machine-drafted by the adapter drafter from capture session {session}. "
        f"The verdict in the subject is over the generated tests and the captured "
        f"fixtures only; nothing here has run against the live source.\n"
    )


def _registry_note(
    registry_path: Path,
    brief: Mapping[str, Any],
    pr_url: str,
    verify_report: verify.VerifyReport,
    warnings: list[str],
) -> str:
    """Local bookkeeping must never be able to lose an opened pull request."""
    try:
        return _record_in_registry(registry_path, brief, pr_url, verify_report)
    except Exception as exc:  # noqa: BLE001 -- a local YAML file, not the PR
        warnings.append(f"registry not updated: {exc}")
        LOGGER.warning("registry not updated for %s: %s", brief.get("adapter_name"), exc)
        return f"failed: {exc}"


def _cleanup(
    *,
    ws: workspace.Workspace,
    brief: Mapping[str, Any],
    loop_report: loop.LoopReport,
    verify_report: verify.VerifyReport,
    draft_dir: Path,
    applied: Sequence[str],
    applied_back: bool,
    staged: Sequence[str],
    pr_url: str,
    committed_to: str,
    pushed: bool,
    registry_note: str,
    warnings: list[str],
    error: BaseException | None,
) -> None:
    """Destroy, record, release -- each tolerating its own failure.

    Run from a ``finally``, so an exception raised in here would REPLACE whatever
    sent us here and the operator would be told about a failed ``git worktree
    remove`` instead of about the failed ``gh pr create`` that actually stopped the
    run. Each step is therefore guarded, and its failure is demoted to a warning in
    the record that the next step writes.
    """
    if error is not None and committed_to:
        warnings.append(
            f"this run left a machine-drafted commit on {committed_to!r}"
            + (" and pushed it to the remote" if pushed else ", not pushed")
            + f"; no pull request was opened. Inspect it before re-running "
            f"(`git log -1 {committed_to}`)"
        )

    if not applied_back:
        # Keyed on whether apply_back RETURNED, not on what it returned. An empty list
        # is a survey that completed and found nothing: the worktree is clean and holds
        # no draft, so destroying it costs nothing. A refusal is the opposite -- the
        # changes are still in there and never came home -- and since nothing ever
        # commits inside a worktree, `git worktree remove --force` would destroy
        # agent-written work that cost real money. Reading `applied == []` for both
        # kept a clean worktree AND its branch on an ordinary successful run, and told
        # the operator it held "the only copy of the draft", which was untrue; the next
        # draft of the same adapter was then refused with WorkspaceExists.
        warnings.append(
            f"apply-back refused, so the worktree at {ws.path} was KEPT: it holds "
            f"changes that never came home and nothing commits inside it. Inspect it, "
            f"then `git worktree remove --force {ws.path}` and "
            f"`git branch -D {ws.branch}` -- in that order, because git refuses to "
            f"delete a branch a worktree is still using"
        )
        return _record_and_release(
            ws=ws,
            brief=brief,
            loop_report=loop_report,
            verify_report=verify_report,
            draft_dir=draft_dir,
            applied=applied,
            worktree_kept=True,
            staged=staged,
            pr_url=pr_url,
            committed_to=committed_to,
            pushed=pushed,
            registry_note=registry_note,
            warnings=warnings,
            error=error,
        )

    if error is not None:
        # Keep both the workspace and lease: the CLI re-verifies this exact tree
        # before retrying a failed commit, push, or PR operation.
        _write_outcome(
            draft_dir,
            _outcome_record(
                ws=ws,
                brief=brief,
                loop_report=loop_report,
                verify_report=verify_report,
                applied=applied,
                worktree_kept=True,
                staged=staged,
                pr_url=pr_url,
                committed_to=committed_to,
                pushed=pushed,
                registry_note=registry_note,
                warnings=warnings,
                error=error,
            ),
        )
        return

    try:
        workspace.destroy(ws)
    except Exception as exc:  # noqa: BLE001 -- must not mask the real failure
        warnings.append(
            f"the worktree at {ws.path} was not removed ({exc}); "
            f"`git worktree remove --force {ws.path}` then `git branch -D {ws.branch}`"
        )
        LOGGER.warning("worktree %s not removed: %s", ws.path, exc)

    _record_and_release(
        ws=ws,
        brief=brief,
        loop_report=loop_report,
        verify_report=verify_report,
        draft_dir=draft_dir,
        applied=applied,
        worktree_kept=False,
        staged=staged,
        pr_url=pr_url,
        committed_to=committed_to,
        pushed=pushed,
        registry_note=registry_note,
        warnings=warnings,
        error=error,
    )


def _record_and_release(
    *,
    ws: workspace.Workspace,
    brief: Mapping[str, Any],
    loop_report: loop.LoopReport,
    verify_report: verify.VerifyReport,
    draft_dir: Path,
    applied: Sequence[str],
    worktree_kept: bool,
    staged: Sequence[str],
    pr_url: str,
    committed_to: str,
    pushed: bool,
    registry_note: str,
    warnings: list[str],
    error: BaseException | None,
) -> None:
    """The two cleanup steps that run whether or not the worktree was destroyed."""
    try:
        _write_outcome(
            draft_dir,
            _outcome_record(
                ws=ws,
                brief=brief,
                loop_report=loop_report,
                verify_report=verify_report,
                applied=applied,
                worktree_kept=worktree_kept,
                staged=staged,
                pr_url=pr_url,
                committed_to=committed_to,
                pushed=pushed,
                registry_note=registry_note,
                warnings=warnings,
                error=error,
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- must not mask the real failure
        LOGGER.warning("outcome record not written to %s: %s", draft_dir, exc)

    try:
        lease.release(draft_dir)
    except Exception as exc:  # noqa: BLE001 -- must not mask the real failure
        LOGGER.warning("lease on %s not released: %s", draft_dir, exc)
