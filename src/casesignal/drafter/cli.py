"""CLI: casesignal-adapter-draft -- the one tool the fourteen drafter modules are.

Subcommands, in the order an operator runs them::

    claim <candidate-id>     take the lease and settle the destination branch
    capture <candidate-id>   fetch fixtures, run the reader pass, MEASURE the brief
    scaffold <adapter>       generate the package, the tests, the memo, the catalog
    draft <adapter>          cut a worktree, stage the scaffold, run the parser loop
    verify <adapter>         run both generated modules and resolve the status
    finish <adapter>         apply back, commit, open the pull request, clean up
    run <candidate-id>       claim -> capture -> scaffold -> draft -> verify

Everything below the argument parsing is wiring, and the wiring is where this
design is most easily defeated. Four of those joins are load-bearing enough to
say out loud here, because each of them fails by reporting success:

*The inventory pass has to be called.* :func:`casesignal.drafter.capture.capture`
writes ``brief.json`` with ``inventory_measured: false`` and no floors, and says
in its own docstring that it relies on a later pass to replace it. That pass is
:func:`casesignal.drafter.inventory.write_measured_brief`, and nothing else in
the repository calls it. Run the capture and the reader without it and every
floor the generator renders is a number nobody measured. It is called from
``capture`` here, in the same process, because the records it measures live in
:class:`~casesignal.drafter.shapes.base.CaptureResult` and are never written to
disk in a form a later invocation could re-read.

*The verification has to go through* :func:`casesignal.drafter.verify.build_report`
*with the real brief.* ``resolve_status`` cannot see ``vacuous_floors``: a report
assembled by hand out of two green test outcomes resolves ``PASS`` over a draft
whose every coverage floor is 0.0. ``brief`` is a required keyword, so silence is
unwriteable, but ``None`` and a trimmed brief both still resolve ``PASS`` -- so
:func:`_require_a_measured_brief` asserts the flag with ``is True`` first, which
also refuses a flag that survived a round trip as the string ``"true"``.

*The barrier has to be staged around.* The scaffold writes into the operator's
checkout; a worktree cut from HEAD therefore has no adapter package, no memo and
no invariant module, and :func:`casesignal.drafter.loop.run_loop` refuses to
start when a named test path is not in the worktree. So the scaffold is copied in
and committed there -- every file of it EXCEPT
``test_<adapter>_expectations.py``, which stays in the main tree and reaches the
loop as ``expectation_module``. Staging that one too would hand the parser pass
the answers it is being graded against.

*A refusal has to be attributed to the pass it came out of.*
``verify.UnusableBrief`` subclasses ``scaffold.UnmeasuredBrief`` subclasses
``scaffold.ScaffoldRefusal``, so an ``except`` chain written in declaration order
reports a verify-stage refusal as a scaffold-stage one and sends the operator to
re-run the wrong thing. :func:`stage_of` delegates to
:func:`casesignal.drafter.finish.refusal_stage`, whose table is ordered
most-derived-first, and only falls back to this module's own table for the
capture, reader and inventory refusals that one does not know about.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from casesignal.drafter import (
    capture,
    client,
    finish,
    inventory,
    lease,
    loop,
    reader,
    scaffold,
    session,
    verify,
    workspace,
)
from casesignal.scout.models import Candidate
from casesignal.scout.registry import Registry

# --- layout ---

DATA_DIR = Path("data/drafts")
REGISTRY_PATH = Path("data/scout/registry.yaml")
WORKTREE_ROOT = Path(".worktrees")

BRIEF_FILE = "brief.json"
WORKSPACE_FILE = "workspace.json"
LOOP_FILE = "loop.json"
ROUNDS_DIR = "rounds"
FIXTURES_DIR = "fixtures"

# Written into tests/fixtures/<adapter>/ and read back before that directory is ever
# pruned. It is the pipeline's own evidence that the directory is its own: see
# _require_a_fixtures_directory_this_pipeline_owns, which refuses without it.
FIXTURES_MARKER = ".drafted-by"

# The loop injects the golden module at the worktree ROOT, where the generated
# module's own ``parents[3] / "fixtures"`` walk lands three directories above the
# worktree. So the copy the loop injects is prepared here with its fixtures root
# rewritten to an absolute path, and it is written OUTSIDE the worktree.
INJECTED_EXPECTATIONS = "expectation_module.py"

# The staging commit's identity. A throwaway worktree branch has to carry a commit
# so `git status` there is clean and the loop's dirty-worktree guard is measuring
# what the agent wrote rather than what this module staged; a checkout with no
# configured user would otherwise fail on it.
_STAGING_IDENTITY = (
    "-c",
    "user.name=CaseSignal Adapter Drafter",
    "-c",
    "user.email=adapter-drafter@localhost",
)

_SHARED_FILE = "src/casesignal/etl/runners/run_pipeline.py"


class CliRefusal(Exception):
    """Raised for a run this module will not start or continue."""


# Stages for the refusals ``finish.refusal_stage`` does not know about. Consulted
# only after it has answered ``"unknown"``, so the ordering that matters -- the
# UnusableBrief / UnmeasuredBrief / ScaffoldRefusal chain -- stays in the one table
# that gets it right.
_CLI_STAGES: tuple[tuple[type[BaseException], str], ...] = (
    # Its own stage, and not "verify". The whole value of this refusal is that it says
    # the failure is the OPERATOR'S ENVIRONMENT rather than the draft; attributing it to
    # a pass would send them to re-run the pass that cannot fix it. It is raised from
    # inside `draft` as well as from `verify`, so no pass name would be true of both.
    (verify.MissingGradingEnvironment, "environment"),
    (capture.IncompleteCapture, "capture"),
    (capture.Refused, "capture"),
    (session.SessionMismatch, "capture"),
    (session.ManifestUnreadable, "capture"),
    (reader.InvalidReaderOutput, "reader"),
    (inventory.InventoryRefusal, "inventory"),
    (client.DrafterUnavailable, "agent"),
    (client.DrafterMisuse, "agent"),
    (CliRefusal, "cli"),
)


def stage_of(exc: BaseException) -> str:
    """Name the pass a refusal came out of, or ``"unknown"``."""
    stage = finish.refusal_stage(exc)
    if stage != "unknown":
        return stage
    for kind, name in _CLI_STAGES:
        if isinstance(exc, kind):
            return name
    return "unknown"


# --- seams ---
#
# Every process this pipeline spawns and every socket it opens goes through one of
# these four, so a test can drive the whole chain without a network, a `claude`
# binary or a `gh` login.


def _http_client_factory() -> capture.ClientFactory:
    """The polite HTTP client the capture and the live check build."""
    from casesignal.etl.services.polite_http import PoliteHTTPClient

    return PoliteHTTPClient


def _drafter_client() -> client.DrafterClient:
    """The agent both file-gap passes run through."""
    return client.SubprocessDrafterClient()


def _runner() -> finish.Runner:
    """How git and ``gh`` are invoked. Injected so no test ever spawns ``gh``."""
    return subprocess.run


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nonce() -> str:
    return os.urandom(4).hex()


# --- the parser ---


def _add_agent_flags(parser: argparse.ArgumentParser) -> None:
    """The bounds every agent round runs under.

    ``--max-budget-usd`` is not decoration. CLI 2.1.251 has no ``--max-turns``, so
    apart from the wall clock it is the only bound that exists, and a bound nobody
    passes is not a bound.
    """
    parser.add_argument("--model", default=client.DEFAULT_MODEL)
    parser.add_argument("--timeout-s", type=int, default=loop.DEFAULT_ROUND_TIMEOUT_S)
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=loop.DEFAULT_PARSER_BUDGET_USD,
        help="per-round ceiling handed to the agent; the only non-wall-clock bound there is",
    )


def _add_capture_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--refresh", action="store_true", help="start a new capture session")
    parser.add_argument("--detail-sample", type=int, default=12)
    parser.add_argument(
        "--session-id",
        default=None,
        help="resume this named capture session, refusing if the draft holds another",
    )
    parser.add_argument(
        "--accept-partial",
        action="append",
        default=[],
        choices=sorted(capture.ACCEPTABLE),
        metavar="FINDING",
        help=(
            "accept one of the capture's quality refusals for this source "
            f"({', '.join(sorted(capture.ACCEPTABLE))}); recorded in brief.json"
        ),
    )
    parser.add_argument("--adapter-name", default=None, help="override the derived identity")


def _add_loop_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rounds", type=int, default=loop.DEFAULT_ROUNDS)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print round 0's prompt and exit without spawning anything",
    )


def _add_verify_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--live-check",
        action="store_true",
        help="re-fetch the index URL under a request budget and report whether it moved",
    )
    parser.add_argument("--max-requests", type=int, default=verify.DEFAULT_LIVE_REQUESTS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casesignal-adapter-draft")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    claim = sub.add_parser("claim", help="take the drafting lease for a candidate")
    claim.add_argument("candidate_id")
    claim.add_argument("--force", action="store_true", help="break a lease another run holds")
    claim.add_argument("--branch", default=None, help="the branch finish will commit onto")
    claim.add_argument("--adapter-name", default=None)

    cap = sub.add_parser("capture", help="capture fixtures, read them, measure the brief")
    cap.add_argument("candidate_id")
    _add_capture_flags(cap)
    _add_agent_flags(cap)

    scaf = sub.add_parser("scaffold", help="generate the package, tests, memo and catalog entry")
    scaf.add_argument("adapter")

    draft = sub.add_parser("draft", help="run the parser pass in a throwaway worktree")
    draft.add_argument("adapter")
    draft.add_argument("--branch", default=None, help="the branch finish will commit onto")
    _add_loop_flags(draft)
    _add_agent_flags(draft)

    ver = sub.add_parser("verify", help="run both generated modules and resolve the status")
    ver.add_argument("adapter")
    _add_verify_flags(ver)

    fin = sub.add_parser("finish", help="apply back, commit, open the pull request")
    fin.add_argument("adapter")

    run = sub.add_parser("run", help="claim, capture, scaffold, draft and verify in one go")
    run.add_argument("candidate_id")
    run.add_argument("--force", action="store_true")
    run.add_argument("--branch", default=None)
    run.add_argument(
        "--finish",
        action="store_true",
        help="also run finish, which commits, PUSHES and opens a pull request",
    )
    _add_capture_flags(run)
    _add_loop_flags(run)
    _add_verify_flags(run)
    _add_agent_flags(run)
    return parser


# --- small shared helpers ---


def _say(message: str) -> None:
    print(message)


def _draft_dir(adapter_name: str, data_dir: Path) -> Path:
    return data_dir / adapter_name


def _load_brief(adapter: str, data_dir: Path) -> dict[str, Any]:
    """Read ``data/drafts/<adapter>/brief.json``, or refuse."""
    path = _draft_dir(adapter, data_dir) / BRIEF_FILE
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CliRefusal(
            f"no brief at {path}: run `casesignal-adapter-draft capture <candidate-id>` "
            f"first. The brief is what every later pass reads the capture out of"
        ) from exc
    except ValueError as exc:
        raise CliRefusal(f"{path} is not readable JSON ({exc})") from exc
    if not isinstance(loaded, dict):
        raise CliRefusal(f"{path} does not hold a JSON object")
    return loaded


def _checked_adapter(name: str) -> str:
    """The ``adapter`` positional, or a refusal, before anything makes a path of it.

    ``capture.adapter_name_for`` checks the name it derives at ``claim`` and
    ``scaffold.Brief`` checks the one in ``brief.json``, but the positional on
    ``scaffold``, ``draft``, ``verify`` and ``finish`` is typed by an operator and
    reaches ``data/drafts/<adapter>``, ``tests/fixtures/<adapter>`` and two
    test-module paths with nothing in between. ``..`` is the one that matters:
    :func:`_copy_fixtures` DELETES under ``tests/fixtures/<adapter>``, and
    ``scaffold ..`` would have pruned every file directly under ``tests/``.

    The rule is capture's own, called rather than restated so the two cannot drift,
    and re-raised as a CLI refusal because a mistyped argument is not a capture-stage
    failure and does not send the operator to re-run the capture.
    """
    try:
        return capture._checked_adapter_name(name, "the adapter argument")
    except capture.Refused as exc:
        raise CliRefusal(str(exc)) from exc


def _require_a_measured_brief(brief: Mapping[str, Any], described: str) -> None:
    """Refuse a brief whose inventory pass never ran, before anything trusts it.

    ``is True`` and not truthiness, deliberately: the flag reaches here through
    JSON, and a string ``"true"`` is truthy while meaning nothing was measured. The
    guard downstream in :func:`verify.build_report` uses the same identity test, so
    a flag that arrived as a string fails open there exactly as ``None`` does -- this
    is where it is caught with a message that names the pass to re-run.
    """
    if brief.get("inventory_measured") is not True:
        raise verify.UnusableBrief(
            f"refusing to {described}: brief.json says inventory_measured="
            f"{brief.get('inventory_measured')!r}, not True. No locator has been applied "
            f"to a captured record, so every floor is a number nobody measured and every "
            f"generated test would assert it. Re-run `capture`, which runs the reader and "
            f"the inventory pass together"
        )


def _load_candidate(registry_path: Path, candidate_id: str) -> Candidate:
    candidate = Registry.load(registry_path).get(candidate_id)
    if candidate is None:
        raise CliRefusal(
            f"no candidate {candidate_id!r} in {registry_path}. Source Scout writes the "
            f"registry; `casesignal-source-scout finalize` is what puts a candidate in it"
        )
    return candidate


def _require_the_lease(draft_dir: Path, adapter_name: str) -> None:
    if lease.read(draft_dir) is None:
        raise CliRefusal(
            f"no drafting lease on {draft_dir}. Run "
            f"`casesignal-adapter-draft claim <candidate-id>` first: the lease is what "
            f"keeps two runs off {adapter_name} at once"
        )


@contextmanager
def _worktree_on_the_path(ws: workspace.Workspace) -> Iterator[None]:
    """Put the worktree's ``src`` ahead of the editable install for child pytest runs.

    ``verify.run_pytest`` spawns ``sys.executable -m pytest`` with the ambient
    environment, and this project is installed editable through a ``.pth`` that
    names the MAIN checkout's ``src``. Without this, a drafting round's pytest
    imports ``casesignal.etl.adapters.<name>`` from the operator's tree -- the
    scaffolded STUB -- and grades the agent's work by a module it never wrote.
    ``PYTHONPATH`` is consulted before ``site-packages`` and before anything a
    ``.pth`` appends, so the worktree wins.
    """
    key = "PYTHONPATH"
    previous = os.environ.get(key)
    entry = str((ws.path / "src").resolve())
    os.environ[key] = entry if not previous else os.pathsep.join([entry, previous])
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


# --- git, through the injected runner ---


def _git(runner: finish.Runner, cwd: Path, *args: str) -> str:
    proc = runner(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if int(getattr(proc, "returncode", 0) or 0) != 0:
        raise CliRefusal(
            f"`git {' '.join(args)}` in {cwd} exited "
            f"{getattr(proc, 'returncode', '?')}: {str(getattr(proc, 'stderr', '')).strip()}"
        )
    return str(getattr(proc, "stdout", "") or "")


def _refuse_a_dirty_index(runner: finish.Runner, repo_root: Path) -> None:
    """Refuse a non-empty index before anything of ours touches the checkout.

    ``finish`` commits with ``git commit -- <paths>``, which is ``--only`` mode, so
    an operator's staged work is not swept into the machine-drafted commit. That
    protects the COMMIT and not the operator: their staging area is still going to
    be walked over by our own ``git add``, and a half-staged refactor is not
    something to discover afterwards.
    """
    staged = _git(runner, repo_root, "diff", "--cached", "--name-only").split()
    if staged:
        raise CliRefusal(
            f"{repo_root} has {len(staged)} path(s) staged in the index "
            f"({', '.join(staged[:5])}{'...' if len(staged) > 5 else ''}). This pipeline "
            f"runs `git add` in your checkout; commit or `git stash` your staged work first"
        )


def _dirty_paths(runner: finish.Runner, repo_root: Path) -> list[str]:
    """Everything git reports as modified or untracked, ignored files excluded."""
    raw = _git(runner, repo_root, "status", "--porcelain", "-z", "--untracked-files=normal")
    return [field[3:] for field in raw.split("\0") if len(field) > 3]


def _refuse_a_dirty_checkout(runner: finish.Runner, repo_root: Path) -> None:
    """Refuse work in progress at the point where nothing of ours is dirty yet.

    Only at ``claim``. From ``scaffold`` onward the checkout is legitimately dirty
    with this pipeline's own output, and a later run of the same check would be
    refusing the draft for existing.
    """
    dirty = _dirty_paths(runner, repo_root)
    if dirty:
        raise CliRefusal(
            f"{repo_root} carries {len(dirty)} uncommitted path(s) "
            f"({', '.join(dirty[:5])}{'...' if len(dirty) > 5 else ''}). A draft commits "
            f"into this checkout; commit or stash your work first so the machine-drafted "
            f"commit is only the draft"
        )


def _kept_worktrees(runner: finish.Runner, repo_root: Path) -> list[tuple[str, str]]:
    """``(path, branch)`` for every drafting worktree still registered.

    Only a refused apply-back keeps one now, and nothing prunes them.
    ``workspace.create`` refuses the same draft name until both the worktree AND
    its branch are gone, so the operator has to be told they exist before they meet
    the collision.
    """
    kept: list[tuple[str, str]] = []
    path = ""
    branch = ""
    for line in _git(runner, repo_root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path, branch = line[len("worktree ") :].strip(), ""
        elif line.startswith("branch "):
            # Only the ref namespace comes off. `rpartition("/")` would turn
            # refs/heads/drafts/<adapter> into <adapter> and print a `git branch -D`
            # naming a branch that does not exist.
            ref = line[len("branch ") :].strip()
            branch = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
        elif not line.strip() and path:
            if WORKTREE_ROOT.name in Path(path).parts:
                kept.append((path, branch))
            path, branch = "", ""
    if path and WORKTREE_ROOT.name in Path(path).parts:
        kept.append((path, branch))
    return kept


def _report_kept_worktrees(runner: finish.Runner, repo_root: Path) -> None:
    for path, branch in _kept_worktrees(runner, repo_root):
        _say(
            f"note: a drafting worktree is still checked out at {path} (branch "
            f"{branch or '?'}). Clear it with `git worktree remove --force {path}` "
            f"then `git branch -D {branch}` -- in that order."
        )


def _destination_branch(
    runner: finish.Runner, repo_root: Path, requested: str | None, adapter_name: str
) -> str:
    """Settle which branch this draft will land on, and refuse a protected one.

    ``finish``'s own protected-branch guard is the backstop and it runs after the
    agent rounds have been bought. This is the layer that can refuse cheaply, and
    it refuses against exactly the same list -- ``finish.protected_branches``, which
    unions the built-in fallbacks, the remote's default,
    ``casesignal.drafter.protected`` in git config and
    ``CASESIGNAL_DRAFTER_PROTECTED_BRANCHES`` in the environment. One list and one
    escape hatch; a second one here would be a rule that disagrees with the rule
    that actually stops the commit.
    """
    protected = finish.protected_branches(repo_root, runner)
    folded = {name.casefold() for name in protected}
    current = finish.current_branch(repo_root, runner)

    if requested is not None and requested != current:
        if requested.casefold() in folded:
            raise CliRefusal(
                f"--branch {requested!r} is a protected branch "
                f"({', '.join(sorted(protected))}); finish would refuse to commit onto it"
            )
        exists = bool(_git(runner, repo_root, "branch", "--list", requested).strip())
        _git(runner, repo_root, "checkout", *([] if exists else ["-b"]), requested)
        _say(f"branch: {'checked out' if exists else 'created'} {requested} in {repo_root}")
        return requested

    branch = requested or current
    if branch.casefold() in folded or branch in {"", "HEAD"}:
        raise CliRefusal(
            f"the checkout at {repo_root} is on {branch!r}, which is protected "
            f"({', '.join(sorted(protected))}). finish commits into THIS checkout and "
            f"pushes it -- the draft's worktree branch is a different branch and is "
            f"destroyed -- so a machine draft would land on {branch!r}. Re-run with "
            f"`--branch draft/{adapter_name}`, or check a branch out yourself. The list "
            f"is {finish.PROTECTED_BRANCH_CONFIG_KEY} in git config and "
            f"{finish.PROTECTED_BRANCH_ENV} in the environment"
        )
    _say(f"branch: {branch} (finish will commit here)")
    return branch


# --- claim ---


def _claim(args: argparse.Namespace, repo_root: Path, data_dir: Path) -> tuple[Candidate, str]:
    runner = _runner()
    candidate = _load_candidate(args.registry, args.candidate_id)
    adapter_name = capture.adapter_name_for(candidate, override=args.adapter_name)
    # Printed BEFORE anything is spent. The naming rule diverges from seven of the
    # eleven adapters already in the repository (wy_dci, oh_ag ...), so an operator
    # who is going to disagree with it should disagree here and not in a pull
    # request title. `--adapter-name` is the override.
    _say(f"adapter: {adapter_name}   (candidate {candidate.id})")

    # BEFORE the crawl and the paid reader round `run` chains after this, and for the
    # same reason the protected-branch check was hoisted here: both of these are facts
    # about the operator's checkout that the adapter name settles on its own, and
    # nothing the capture discovers can change either answer. `run <candidate whose
    # name derives to a shipped adapter>` and `run <cand> --adapter-name fdle` are the
    # exact re-draft and name-collision cases the refusal text describes, and both used
    # to spend a full reader round before saying so.
    _preflight_the_checkout(repo_root, adapter_name, candidate.state)

    _report_kept_worktrees(runner, repo_root)
    _refuse_a_dirty_index(runner, repo_root)
    _refuse_a_dirty_checkout(runner, repo_root)
    branch = _destination_branch(runner, repo_root, args.branch, adapter_name)

    draft_dir = _draft_dir(adapter_name, data_dir)
    held = lease.acquire(draft_dir, adapter_name, branch, force=args.force)
    _say(f"claimed: {draft_dir} (pid {held.pid} on {held.host})")
    return (candidate, adapter_name)


def _preflight_the_checkout(repo_root: Path, adapter_name: str, state: str) -> None:
    """The two refusals that are decidable from the adapter name, asked before any spend.

    :func:`_require_a_fixtures_directory_this_pipeline_owns` and
    :func:`scaffold.check_existing_targets` are both re-run at their own stage -- the
    first inside the function that DELETES, which is where a guard belongs, and the
    second inside the function that writes. Neither is moved; both are additionally
    asked here, where a refusal costs nothing.
    """
    _require_a_fixtures_directory_this_pipeline_owns(
        repo_root / "tests" / "fixtures" / adapter_name, adapter_name
    )
    scaffold.check_existing_targets(repo_root, adapter_name, state)


# --- capture, the reader pass, and the inventory pass ---


def _capture(
    args: argparse.Namespace,
    repo_root: Path,
    data_dir: Path,
    candidate: Candidate | None = None,
) -> str:
    candidate = candidate or _load_candidate(args.registry, args.candidate_id)
    adapter_name = capture.adapter_name_for(candidate, override=args.adapter_name)
    _say(f"adapter: {adapter_name}   (candidate {candidate.id})")

    draft_dir = _draft_dir(adapter_name, data_dir)
    _require_the_lease(draft_dir, adapter_name)
    fixtures_dir = draft_dir / FIXTURES_DIR

    outcome = capture.capture(
        candidate,
        draft_dir=draft_dir,
        fixtures_dir=fixtures_dir,
        client_factory=_http_client_factory(),
        now=_now(),
        nonce=_nonce(),
        detail_sample=args.detail_sample,
        session_id=args.session_id,
        refresh=args.refresh,
        adapter_name=args.adapter_name,
        accept_partial=args.accept_partial,
    )
    result = outcome.result
    _say(
        f"captured: {result.records_captured} record(s) as {outcome.shape} over "
        f"{outcome.transport}; {len(result.listing_paths)} listing and "
        f"{len(result.detail_paths)} detail fixture(s) in {fixtures_dir}"
    )

    root = outcome.session.fixtures_root
    fixture_paths = [
        (f"{root}/{name}" if root else name)
        for name in [*result.listing_paths, *result.detail_paths]
    ]
    locators, expectations = reader.run_reader(
        candidate,
        _drafter_client(),
        fixture_paths=fixture_paths,
        out_dir=draft_dir,
        cwd=draft_dir,
        model=args.model,
        timeout_s=args.timeout_s,
        max_budget_usd=args.max_budget_usd,
    )
    _say(f"read: {len(locators)} locator(s), {len(expectations)} transcribed record(s)")

    # NOTHING ELSE IN THE REPOSITORY CALLS THIS. Without it brief.json keeps
    # `inventory_measured: false`, the generator refuses (or, one bad edit away,
    # renders floors nobody measured), and the whole pipeline reports a pass over
    # an adapter that was never graded.
    _, measurement = inventory.write_measured_brief(
        draft_dir,
        candidate,
        outcome,
        locators,
        now=_now(),
        adapter_name=args.adapter_name,
        accepted=args.accept_partial,
    )
    _say(f"measured: {len(measurement.floors)} coverage floor(s) derived")
    for label, names in (
        ("no locator was returned for", measurement.omitted),
        (
            "measured BELOW its fixed floor (its test is red from the first run)",
            measurement.unreachable_floors,
        ),
        ("derived a floor of 0.0, which no parser can fail", measurement.vacuous_floors),
        (
            "scored markedly better on another page than the one it was filed under",
            measurement.suspected_page_mismatch,
        ),
    ):
        if names:
            _say(f"  advisory: {', '.join(names)} {label}")
    return adapter_name


# --- scaffold ---


def _brief_object(adapter_name: str, data_dir: Path) -> scaffold.Brief:
    draft_dir = _draft_dir(adapter_name, data_dir)
    raw = _load_brief(adapter_name, data_dir)
    _require_a_measured_brief(raw, "scaffold")
    expectations = reader.load_expectations(draft_dir / reader.EXPECTATIONS_FILENAME)
    return scaffold.Brief.from_mapping(raw, expectations=expectations)


def _scaffold(args: argparse.Namespace, repo_root: Path, data_dir: Path) -> None:
    runner = _runner()
    adapter_name = _checked_adapter(args.adapter)
    draft_dir = _draft_dir(adapter_name, data_dir)
    _require_the_lease(draft_dir, adapter_name)
    _refuse_a_dirty_index(runner, repo_root)

    brief = _brief_object(adapter_name, data_dir)
    written = scaffold.scaffold(brief, repo_root=repo_root)
    copied, pruned = _copy_fixtures(
        draft_dir, repo_root, adapter_name, [*brief.listing_paths, *brief.detail_paths]
    )
    if brief.runtime:
        from casesignal.drafter.runtime import ReplayClient

        capture_file = repo_root / "tests" / "fixtures" / adapter_name / "capture.json"
        capture_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_id": brief.session_id,
                    "fixtures": list(brief.fixture_manifest),
                    "detail_sample": len(brief.detail_paths),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (capture_file.parent / ".gitattributes").write_text("* -text\n", encoding="utf-8")
        replay_client = ReplayClient(capture_file.parent)
        for fixture in brief.fixture_manifest:
            replay_client.get(str(fixture["url"]))
    for path in written:
        _say(f"  wrote {path}")
    _say(
        f"  wrote tests/fixtures/{adapter_name}/ ({copied} file(s)"
        f"{f', {pruned} stale file(s) removed' if pruned else ''})"
    )
    _say(
        f"note: {_SHARED_FILE} is the one file this draft SHARES with the rest of the "
        f"repository -- the adapter registration is appended to it. Any unrelated "
        f"uncommitted edit of yours in that file will be committed with the draft."
    )


_FIXTURES_MARKER_TEXT = """This directory is written by the SP2 Adapter Drafter, and PRUNED by it.

`casesignal-adapter-draft scaffold {adapter}` copies the pages
data/drafts/{adapter}/brief.json names into this directory and DELETES every other
file in it, so nothing put here by hand survives. This marker is how the tool knows
the directory is its own: without it, it refuses to prune the directory at all.
"""


def _require_a_fixtures_directory_this_pipeline_owns(target: Path, adapter_name: str) -> None:
    """Refuse to prune a ``tests/fixtures/<adapter>`` this pipeline did not write.

    :func:`_copy_fixtures` DELETES, and the directory it deletes in is named by the
    adapter name -- which an operator sets with ``--adapter-name``. ``tests/fixtures/``
    already holds ``fdle``, ``scout``, ``html`` and ``xml``, none of which is an
    adapter package name, so ``--adapter-name fdle`` would have deleted eleven tracked
    fixtures belonging to another suite. It also holds ``cold_case_ar_asp``,
    ``cold_case_mn_bca``, ``cold_case_nh_doj`` and ``cold_case_ok_osbi``, which is the
    likelier collision: re-drafting an adapter that already shipped, whose curated
    fixtures its own hand-written tests read. The generator's own overwrite refusal
    does NOT cover either: it guards the files it writes, and this directory is not
    one of them.

    So ownership is positive evidence -- a marker file this pipeline wrote -- rather
    than an inference from a guard that is looking at other files. Inferring it from a
    distant guard is what was wrong the first time.
    """
    if target.is_symlink():
        raise CliRefusal(
            f"{target} is a symlink. Scaffolding {adapter_name} prunes that directory, "
            f"and the walk follows the link, so the files deleted would be the real "
            f"ones at the far end. Replace it with a real directory, or draft under "
            f"another `--adapter-name`"
        )
    if not target.exists():
        return
    if not target.is_dir():
        raise CliRefusal(
            f"{target} exists and is not a directory. Both generated modules read "
            f"their fixtures out of it. Move it aside, or draft under another "
            f"`--adapter-name`"
        )
    marker = target / FIXTURES_MARKER
    if marker.is_symlink():
        # Checked before is_file(), which FOLLOWS the link: any existing file on the
        # far end would otherwise stand in as this pipeline's evidence that the
        # directory is its own to empty. The leaf directory is checked the same way,
        # and a guard that checks one and not the other is a guard with a seam.
        raise CliRefusal(
            f"{marker} is a symlink. That file is this pipeline's only evidence that "
            f"{target} is its own to prune, and a link to a file somewhere else is "
            f"not that evidence. Remove it, or draft under another `--adapter-name`"
        )
    if marker.is_file():
        return
    raise CliRefusal(
        f"{target} already exists and this pipeline did not write it (it holds no "
        f"{FIXTURES_MARKER}). Scaffolding {adapter_name} PRUNES that directory -- every "
        f"file brief.json does not name is deleted -- so it will not touch a directory "
        f"it did not create. There are two ways to be here. (1) The name collides with "
        f"fixtures belonging to another suite: tests/fixtures/ holds `fdle`, `scout`, "
        f"`html` and `xml`, none of which is an adapter package, and nothing upstream "
        f"refuses those names. Draft under another `--adapter-name`. (2) You are "
        f"re-drafting an adapter that has already shipped: `cold_case_ok_osbi` and the "
        f"other `cold_case_*` directories hold curated fixtures that the shipped "
        f"adapter's own tests read. Keep the name -- but move that directory aside or "
        f"delete it yourself first, deliberately, because replacing those fixtures with "
        f"this capture's is a change for a reviewer to look at rather than a retry"
    )


def _copy_fixtures(
    draft_dir: Path, repo_root: Path, adapter_name: str, wanted: Sequence[str]
) -> tuple[int, int]:
    """Put THIS capture's fixtures where the generated tests look, and remove the rest.

    Both generated modules resolve ``FIXTURES_ROOT`` as
    ``tests/fixtures/<adapter>``; the capture wrote them under
    ``data/drafts/<adapter>/fixtures``. The memo says to copy them by hand, which
    is a step nobody would do before the first drafting round and every round would
    then fail on a missing file.

    ``wanted`` is the brief's own ``listing_paths`` + ``detail_paths``, which is what
    the generator rendered ``LISTING_FIXTURES`` and ``DETAIL_FIXTURES`` from, so the
    directory ends up holding exactly the pages the tests name. Neither
    ``session.start`` nor this function used to delete anything: a ``capture
    --refresh`` that walked fewer pages left the superseded ones on disk under both
    roots, ``finish`` stages the whole directory with ``--untracked-files=all``, and
    the pull request then shipped fixture files from a capture nobody measured --
    which a reviewer diffing them against ``manifest.json`` reads as current evidence.

    A ``.drafted-by`` marker is written into the directory alongside the fixtures,
    and it ships with them. It is what
    :func:`_require_a_fixtures_directory_this_pipeline_owns` reads on the next run to
    decide whether this pipeline may delete in there at all.

    Returns ``(copied, pruned)``. Only files are pruned, only from this adapter's own
    fixtures directory, and only after that directory has been shown to be ours.
    """
    # Checked HERE and not only in the caller: this is the function that deletes, and
    # what stands between `scaffold ..` and every file directly under tests/ should be
    # a guard rather than the caller having remembered.
    adapter_name = _checked_adapter(adapter_name)
    source = draft_dir / FIXTURES_DIR
    target = repo_root / "tests" / "fixtures" / adapter_name
    _require_a_fixtures_directory_this_pipeline_owns(target, adapter_name)
    # De-duplicated: the generator flattens the same way (scaffold._fixture_names), so
    # two captured pages with the same basename are ONE file here and in the generated
    # tuple. Counting them twice would report a file to the operator that is not there.
    names = list(dict.fromkeys(Path(name).name for name in wanted))
    if FIXTURES_MARKER in names:
        raise CliRefusal(
            f"brief.json names a fixture called {FIXTURES_MARKER}, which is this "
            f"pipeline's own marker in {target}. Re-capture; nothing has been written"
        )
    missing = [name for name in names if not (source / name).is_file()]
    if missing:
        raise CliRefusal(
            f"brief.json names {len(missing)} fixture(s) that are not under {source} "
            f"({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}). The "
            f"generated tests read them by name, so every round would fail on a missing "
            f"file. Re-run `casesignal-adapter-draft capture <candidate-id> --refresh`"
        )
    target.mkdir(parents=True, exist_ok=True)
    (target / FIXTURES_MARKER).write_text(
        _FIXTURES_MARKER_TEXT.format(adapter=adapter_name), encoding="utf-8"
    )
    for name in names:
        shutil.copy2(source / name, target / name)
    keep = {*names, FIXTURES_MARKER}
    pruned = 0
    for entry in sorted(target.iterdir()):
        if entry.is_file() and entry.name not in keep:
            try:
                entry.unlink()
            except OSError as exc:
                # Refused rather than raised: this is the one file-DELETING path in the
                # module, and it is the last one that should report itself as a
                # traceback with no stage on it. Every fixture the brief names has
                # already been copied and the prune is idempotent, so the re-run this
                # message asks for finishes the job.
                raise CliRefusal(
                    f"could not remove the superseded fixture {entry} ({exc}). "
                    f"{pruned} stale file(s) were removed before it and every fixture "
                    f"brief.json names has been copied, so re-running `scaffold` once "
                    f"the permission is fixed finishes the prune"
                ) from exc
            pruned += 1
    return (len(names), pruned)


# --- the drafting loop ---


def _scaffold_paths(brief: Mapping[str, Any], adapter_name: str) -> list[str]:
    """Everything the scaffold pass wrote, EXCEPT the golden module.

    ``test_<adapter>_expectations.py`` is the answer key. It stays in the main
    checkout and reaches ``run_loop`` as ``expectation_module``, which injects it
    for the duration of a test run and removes it again. Staged here it would sit
    in the tree the agent is reading for the whole run, and every golden test could
    be satisfied by copying.
    """
    state = str(brief.get("state") or "").lower()
    paths = [
        f"{loop.ADAPTER_PACKAGE_ROOT}/{adapter_name}",
        f"tests/unit/etl/adapters/test_{adapter_name}_invariants.py",
        f"tests/fixtures/{adapter_name}",
        f"docs/drafts/{adapter_name}.md",
        _SHARED_FILE,
    ]
    if state:
        paths.append(f"src/casesignal/etl/sources/cold_case_{state}.yaml")
    return paths


def _require_the_scaffold(repo_root: Path, adapter_name: str) -> None:
    """Refuse a draft the scaffold pass never wrote, before anything is cut or checked out.

    ``_stage_the_scaffold`` copies whatever of the scaffold it finds and skips what it
    does not, and ``_prepare_expectation_module`` reads the golden module straight off
    disk. So an operator who skipped ``scaffold`` -- or who deleted the adapter package
    to clear a refused re-draft, which the run-book itself tells them to do -- got a
    worktree, a branch, a staging commit over nothing, a "staged 0 scaffold path(s)"
    line nobody reads, and then a bare ``FileNotFoundError`` with no stage on it. This
    is checked in two places: here, before the worktree exists, and again inside
    ``_stage_the_scaffold``, which is the function whose skipping is what made staging
    nothing possible.

    The three paths are the ones a drafting round cannot run without: ``adapter.py``
    in the package the parser writes into -- the module itself rather than its
    directory, because an operator who deleted only the stub to clear a re-draft
    leaves the directory behind -- the invariant module the round is graded by, and
    the golden module the loop injects. The memo, the fixtures and the catalog entry are not
    checked here -- a round without them fails loudly rather than silently.
    """
    missing = [
        rel
        for rel in (
            f"{loop.ADAPTER_PACKAGE_ROOT}/{adapter_name}/adapter.py",
            f"tests/unit/etl/adapters/test_{adapter_name}_invariants.py",
            f"tests/unit/etl/adapters/test_{adapter_name}_expectations.py",
        )
        if not (repo_root / rel).exists()
    ]
    if missing:
        raise CliRefusal(
            f"{repo_root} is missing {len(missing)} of the scaffold's paths "
            f"({', '.join(missing)}), so there is nothing for the parser pass to write "
            f"into and nothing to grade it by. Run `casesignal-adapter-draft scaffold "
            f"{adapter_name}` first"
        )


# The repository's own tests/conftest.py redirects DATABASE_URL and then REFUSES the
# session unless that database is reachable and sentinel-stamped. The two generated
# modules read fixtures off disk and touch no database, but the guard runs in
# pytest_configure, so with Postgres down every drafting round exits 4 -- a pytest
# usage error, reported as "nothing ran", after the round has been bought. The
# throwaway worktree gets this instead: the sys.path half, which is what makes the
# worktree's own casesignal win, and nothing else.
_WORKTREE_CONFTEST = '''"""Drafting worktree conftest, written by the SP2 Adapter Drafter.

This replaces the repository's own tests/conftest.py for the duration of one
throwaway draft. It keeps the sys.path insertion, so the generated tests import
the adapter from THIS worktree, and drops the test-database redirection and
enforcement, which would fail the whole session over a database no generated test
opens.

Dropping that guard is why the grading subprocess runs on an environment ALLOWLIST
rather than the operator's own (``verify._INHERITED_ENV``). The two decisions are
one decision: this file removes the project's only DB safety net for a run that
executes agent-written code, so that run does not get a ``DATABASE_URL`` to point
at -- nor any API key in the operator's shell. Executing what the agent wrote is
inherent to the design and is not in question; handing it credentials is a widening
nothing here needs. Edit either half only with the other in view.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(_ROOT), str(_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
'''


def _stage_the_scaffold(
    runner: finish.Runner, ws: workspace.Workspace, brief: Mapping[str, Any], adapter_name: str
) -> list[str]:
    """Copy the scaffold into the worktree and commit it there.

    Committed, not merely copied. ``run_loop`` refuses to start over a worktree
    already dirty outside the paths the parser may write, and every round's
    ``changed_paths`` is measured against the same allowlist -- so staged files left
    uncommitted would end round 0 with ``wrote-outside-allowlist`` attributed to an
    agent that had not written anything yet. Nothing is lost by committing: the
    scaffold's own copy is in the operator's checkout, which is where ``finish``
    stages it from.

    A path that is not in the checkout is skipped rather than refused -- the catalog
    entry is absent for a stateless source -- so the refusal that makes staging
    nothing impossible is :func:`_require_the_scaffold`, called first.
    """
    _require_the_scaffold(ws.repo_root, adapter_name)
    staged: list[str] = []
    for rel in _scaffold_paths(brief, adapter_name):
        source = ws.repo_root / rel
        if not source.exists():
            continue
        target = ws.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
        staged.append(rel)

    conftest = ws.path / "tests" / "conftest.py"
    conftest.parent.mkdir(parents=True, exist_ok=True)
    conftest.write_text(_WORKTREE_CONFTEST, encoding="utf-8")

    _git(runner, ws.path, "add", "-A")
    _git(
        runner,
        ws.path,
        *_STAGING_IDENTITY,
        "commit",
        "--no-verify",
        "-m",
        f"stage: scaffold for {adapter_name} (throwaway drafting worktree)",
    )
    return staged


def _prepare_expectation_module(
    ws: workspace.Workspace, draft_dir: Path, adapter_name: str
) -> Path:
    """The golden module the loop injects, with its fixtures root made absolute.

    ``run_loop`` copies this file to the worktree ROOT for the duration of each
    test run, because anywhere inside ``tests/`` would leave it readable by the
    agent between rounds. The generated module resolves its fixtures as
    ``Path(__file__).parents[3] / "fixtures" / <adapter>``, which is true where the
    scaffold writes it and three directories above the worktree once it has been
    injected. Rewritten here rather than in the template, because the template's
    path is right for the file's real home and only wrong for this one copy.
    """
    source = ws.repo_root / f"tests/unit/etl/adapters/test_{adapter_name}_expectations.py"
    text = source.read_text(encoding="utf-8")
    rendered = (
        f'FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "{adapter_name}"'
    )
    if rendered not in text:
        raise CliRefusal(
            f"{source} does not carry the generated FIXTURES_ROOT line, so the copy the "
            f"loop injects would look for fixtures three directories above the worktree "
            f"and every golden test would fail on a missing file. Re-run `scaffold`"
        )
    absolute = (ws.path / "tests" / "fixtures" / adapter_name).resolve()
    patched = text.replace(rendered, f"FIXTURES_ROOT = Path({str(absolute)!r})", 1)
    target = draft_dir / INJECTED_EXPECTATIONS
    target.write_text(patched, encoding="utf-8")
    return target


def _draft(args: argparse.Namespace, repo_root: Path, data_dir: Path) -> loop.LoopReport:
    runner = _runner()
    adapter_name = _checked_adapter(args.adapter)
    draft_dir = _draft_dir(adapter_name, data_dir)
    brief = _load_brief(adapter_name, data_dir)
    _require_a_measured_brief(brief, "draft a parser")
    # Before the lease and the worktree, not inside run_loop where it is checked again:
    # a bound only enforced after a worktree exists charges a cleanup for finding a typo.
    loop.check_round_bounds(args.rounds, args.max_budget_usd)

    if args.dry_run:
        # Before the lease, the branch and the worktree, because none of them is
        # needed to render a prompt and an operator reading one should not have to
        # have claimed anything.
        _say(
            loop.build_round_prompt(brief=brief, exemplar=loop.choose_exemplar(brief), failures=[])
        )
        return loop.LoopReport(rounds=[], passed=False, stopped_because="dry-run")

    _require_the_lease(draft_dir, adapter_name)
    _refuse_a_dirty_index(runner, repo_root)
    _report_kept_worktrees(runner, repo_root)
    # Both BEFORE workspace.create, and the scaffold check before _destination_branch
    # as well, because that one CHECKS OUT a branch. A refusal after the worktree
    # exists costs a cleanup the operator has to do by hand; a refusal after the loop
    # has run costs the whole agent session.
    _require_the_scaffold(repo_root, adapter_name)
    _destination_branch(runner, repo_root, args.branch, adapter_name)

    expectations = reader.load_expectations(draft_dir / reader.EXPECTATIONS_FILENAME)
    if (draft_dir / WORKSPACE_FILE).exists():
        ws = _load_workspace(draft_dir)
        if not ws.path.is_dir() or ws.repo_root.resolve() != repo_root.resolve():
            raise CliRefusal("recorded draft workspace is unavailable; inspect outcome.json")
        claimed = lease.read(draft_dir)
        if claimed is None or finish.current_branch(repo_root, runner) != claimed.branch:
            raise CliRefusal("switch to the claimed destination branch before resuming")
        staged = []
    else:
        ws = workspace.create(
            repo_root, f"drafts/{adapter_name}", repo_root / WORKTREE_ROOT / adapter_name
        )
        staged = _stage_the_scaffold(runner, ws, brief, adapter_name)
    _write_json(
        draft_dir / WORKSPACE_FILE,
        {
            "branch": ws.branch,
            "path": str(ws.path),
            "repo_root": str(ws.repo_root),
        },
    )
    _say(f"worktree: {ws.path} on {ws.branch}; staged {len(staged)} scaffold path(s)")
    module = _prepare_expectation_module(ws, draft_dir, adapter_name)

    with _worktree_on_the_path(ws):
        report = loop.run_loop(
            ws=ws,
            client=_drafter_client(),
            brief=brief,
            exemplar=loop.choose_exemplar(brief),
            expectation_module=module,
            # Named explicitly. run_pytest refuses an empty list because pytest with
            # no path falls back to `testpaths` and would run the whole repository
            # suite inside a drafting round.
            test_paths=[Path(f"tests/unit/etl/adapters/test_{adapter_name}_invariants.py")],
            rounds=args.rounds,
            timeout_s=args.timeout_s,
            artifacts_dir=draft_dir / ROUNDS_DIR,
            # Passed, not defaulted: without it the redaction's value scan is off and
            # a failure line quoting a golden value goes back into the next prompt.
            expectations=expectations,
            model=args.model,
            max_budget_usd=args.max_budget_usd,
        )
    _write_json(draft_dir / LOOP_FILE, _loop_json(report))
    _say(
        f"loop: {len(report.rounds)} round(s), stopped_because={report.stopped_because}, "
        f"passed={report.passed}"
    )
    for outcome in report.rounds:
        _say(f"  round {outcome.index}: {finish.round_reason(outcome)}")
    return report


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _loop_json(report: loop.LoopReport) -> dict[str, Any]:
    return {
        "passed": report.passed,
        "stopped_because": report.stopped_because,
        "rounds": [
            {
                "index": outcome.index,
                "passed": outcome.passed,
                "signature": outcome.signature,
                "timed_out": outcome.timed_out,
            }
            for outcome in report.rounds
        ],
    }


def _load_loop_report(draft_dir: Path) -> loop.LoopReport:
    path = draft_dir / LOOP_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliRefusal(
            f"no loop report at {path}: run `casesignal-adapter-draft draft <adapter>` "
            f"first. The pull request body says what each round did, and there is "
            f"nothing to say without it"
        ) from exc
    return loop.LoopReport(
        rounds=[loop.RoundOutcome(**entry) for entry in data.get("rounds", [])],
        passed=bool(data.get("passed")),
        stopped_because=str(data.get("stopped_because") or "unknown"),
    )


def _load_workspace(draft_dir: Path) -> workspace.Workspace:
    path = draft_dir / WORKSPACE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliRefusal(
            f"no worktree recorded at {path}: run `casesignal-adapter-draft draft "
            f"<adapter>` first. The drafted parser lives in the worktree and nowhere else"
        ) from exc
    return workspace.Workspace(
        branch=str(data["branch"]), path=Path(data["path"]), repo_root=Path(data["repo_root"])
    )


# --- verification ---


def _run_the_generated_modules(
    ws: workspace.Workspace, adapter_name: str
) -> tuple[verify.TestOutcome, verify.TestOutcome]:
    """Run the invariant module and the golden module, each on its own.

    Separately, because ``build_report`` resolves the status out of two outcomes
    and a single run collapses them: a red golden test and a red structural
    invariant mean different things, and the pull request body says which.

    The golden module is copied into the worktree at the path the scaffold gave it
    and removed again in a ``finally``. The barrier is over by now -- no agent is
    running -- and at that path its own ``parents[3]`` walk finds the fixtures with
    no rewriting. Left behind it would be an unexpected file in the worktree, and
    ``apply_back`` refuses the whole draft for one.
    """
    invariants_rel = Path(f"tests/unit/etl/adapters/test_{adapter_name}_invariants.py")
    golden_rel = Path(f"tests/unit/etl/adapters/test_{adapter_name}_expectations.py")
    with _worktree_on_the_path(ws):
        invariants = verify.run_pytest([invariants_rel], ws.path)
        source = ws.repo_root / golden_rel
        target = ws.path / golden_rel
        if target.exists():
            raise CliRefusal(
                f"{target} already exists in the worktree. Nothing stages the golden "
                f"module there, so either a previous verify did not clean up or the "
                f"parser pass wrote it, and running it would grade the draft by a file "
                f"the draft may have authored"
            )
        try:
            shutil.copy2(source, target)
            expectations = verify.run_pytest([golden_rel], ws.path)
        finally:
            target.unlink(missing_ok=True)
    return (invariants, expectations)


def _verify(
    args: argparse.Namespace, repo_root: Path, data_dir: Path, adapter_name: str
) -> verify.VerifyReport:
    adapter_name = _checked_adapter(adapter_name)
    draft_dir = _draft_dir(adapter_name, data_dir)
    brief = _load_brief(adapter_name, data_dir)
    _require_a_measured_brief(brief, "verify")
    ws = _load_workspace(draft_dir)

    invariants, expectations = _run_the_generated_modules(ws, adapter_name)
    # BOTH parser modules. find_todos reads one path by convention, and a marked
    # TODO in scrape.py that nobody scanned resolves the draft to PASS.
    todos = [
        todo
        for module in loop.parser_module_paths(ws.path, adapter_name)
        for todo in verify.find_todos(module)
    ]
    # Never resolve_status, and never a hand-assembled VerifyReport: neither can see
    # the brief's vacuous floors, and a draft whose every floor is 0.0 resolves PASS
    # through either of them.
    report = verify.build_report(
        invariants=invariants, expectations=expectations, todos=todos, brief=brief
    )
    _say(f"verify: {report.summary()}")
    for advisory in report.advisories:
        _say(f"  advisory: {advisory}")
    for todo in report.todos:
        _say(f"  TODO({todo.field}) at line {todo.line}")
    if getattr(args, "live_check", False):
        lines = _live_check(draft_dir, brief, args.max_requests)
    else:
        lines = _saved_live_check(draft_dir, brief)
    for line in lines:
        _say(f"  live: {line}")
    return replace(report, live_probe=tuple(lines))


def _source_drift_check(draft_dir: Path, brief: Mapping[str, Any], max_requests: int) -> list[str]:
    """Re-fetch the index URL under a request budget and say whether it moved.

    Advisory, and deliberately not part of the status: this asks whether the SOURCE
    has changed since the capture, which is a fact about the world rather than
    about the draft. The budget is imposed below the client, so a paginating
    follow-up added here could not run away.

    Advisory all the way down, which is why every failure of the fetch itself comes
    back as a line rather than an exception: an offline machine, a DNS hiccup, a TLS
    failure or a robots refusal used to abort ``verify`` with a traceback and a
    non-zero exit over a report that had already resolved PASS and been printed.
    Nothing this function learns can change that status, so nothing it fails at may
    change the exit code either.
    """
    url = str(brief.get("index_url") or "")
    host = urlparse(url).hostname
    if not host:
        return [f"no usable index_url in the brief ({url!r}); nothing to check"]
    held = session.load(draft_dir)
    if held is None:
        return ["no capture manifest on disk; nothing to compare a live fetch against"]

    factory = _http_client_factory()
    lines: list[str] = []
    inner: Any = None
    budget: verify.RequestBudget | None = None
    response: Any = None
    # THE FETCH ONLY, and the client construction with it -- the polite client
    # resolves the host as it is built and can refuse the URL there. The comparison
    # below is deliberately outside: it is this module's own code, and an
    # AttributeError in it is a defect that should be loud rather than a `live:`
    # advisory saying the source might have moved.
    try:
        inner = factory(
            rate_limit_seconds=2.0,
            allowed_hosts=frozenset({host}),
            bypass_robots_hosts=frozenset(),
            tls_impersonate=str(brief.get("transport")) == "curl_cffi",
        )
        budget = verify.RequestBudget(inner, max_requests)
        response = budget.get(url)
    except verify.BudgetExceeded as exc:
        lines.append(f"request budget exhausted: {exc}")
    except Exception as exc:  # noqa: BLE001 -- advisory: a fetch may not move the status
        lines.append(
            f"the live fetch FAILED ({type(exc).__name__}: {exc}). This says nothing "
            f"about the draft -- the status above stands, and whether the source has "
            f"moved is still unknown"
        )
    finally:
        # The budget delegates close() to the client it wraps; the raw client is the
        # one to close when RequestBudget itself is what raised. Suppressed for the
        # same reason as the fetch: a client that cannot close is not a verdict on the
        # draft.
        closer = budget if budget is not None else inner
        if closer is not None:
            with suppress(Exception):
                closer.close()
    if response is not None:
        digest = hashlib.sha256(response.content).hexdigest()
        recorded = next((f.sha256 for f in held.fixtures if f.url == url), None)
        lines.append(f"{url} answered {response.status_code}")
        if recorded is None:
            lines.append("the manifest holds no digest for the index URL; nothing to compare")
        elif recorded == digest:
            lines.append("byte-identical to the captured fixture; the draft is current")
        else:
            lines.append(
                "the live page NO LONGER matches the captured fixture. The draft was "
                "graded against a document the source has since changed; re-capture "
                "before trusting the golden values"
            )
    if budget is not None:
        lines.append(f"{budget.spent} of {budget.limit} budgeted request(s) used")
    return lines


def _adapter_digest(draft_dir: Path, brief: Mapping[str, Any]) -> str:
    root = (
        _load_workspace(draft_dir).path / "src/casesignal/etl/adapters" / str(brief["adapter_name"])
    )
    digest = hashlib.sha256(json.dumps(dict(brief), sort_keys=True).encode())
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _saved_live_check(draft_dir: Path, brief: Mapping[str, Any]) -> list[str]:
    path = draft_dir / "live.json"
    if not path.exists():
        return []
    try:
        saved = json.loads(path.read_text())
        if saved["session_id"] != brief.get("session_id") or saved[
            "adapter_digest"
        ] != _adapter_digest(draft_dir, brief):
            return []
        lines = saved["lines"]
        return lines if isinstance(lines, list) and all(isinstance(x, str) for x in lines) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _live_check(draft_dir: Path, brief: Mapping[str, Any], max_requests: int) -> list[str]:
    from casesignal.drafter.live import probe

    try:
        lines = probe(_load_workspace(draft_dir), dict(brief), max_requests)
    except Exception as exc:
        lines = [f"the live fetch FAILED ({type(exc).__name__}: {exc}); adapter not live-verified"]
    _write_json(
        draft_dir / "live.json",
        {
            "session_id": brief.get("session_id"),
            "lines": lines,
            "adapter_digest": _adapter_digest(draft_dir, brief),
        },
    )
    return lines


# --- finish ---


def _finish(args: argparse.Namespace, repo_root: Path, data_dir: Path, adapter_name: str) -> str:
    runner = _runner()
    adapter_name = _checked_adapter(adapter_name)
    draft_dir = _draft_dir(adapter_name, data_dir)
    brief = _load_brief(adapter_name, data_dir)
    ws = _load_workspace(draft_dir)
    loop_report = _load_loop_report(draft_dir)
    # Recomputed rather than read back off disk. A report re-hydrated from JSON is a
    # hand-assembled report wearing a file's clothes, and the pull request body has
    # to describe the tree that is about to be committed rather than the tree some
    # earlier invocation saw.
    verify_report = _verify(args, repo_root, data_dir, adapter_name)

    _say(
        f"note: {_SHARED_FILE} is staged with this draft. Any unrelated uncommitted "
        f"edit of yours in it is about to be committed."
    )
    pr_url = finish.finish(
        ws=ws,
        brief=brief,
        loop_report=loop_report,
        verify_report=verify_report,
        draft_dir=draft_dir,
        registry_path=args.registry,
        runner=runner,
    )
    _report_the_outcome(draft_dir, pr_url)
    _report_kept_worktrees(runner, repo_root)
    return pr_url


def _report_the_outcome(draft_dir: Path, pr_url: str) -> None:
    """Say where the commit landed without making the operator open a file.

    ``committed_to`` is the OPERATOR's branch, not the draft's worktree branch, and
    ``pushed`` says whether it reached the remote. A run that committed and pushed
    and then failed to open a pull request leaves a machine-drafted commit on a
    branch the operator is standing on, and that residue has to be visible from the
    line that reports the failure.
    """
    _say(f"pull request: {pr_url or '(none opened)'}")
    try:
        record = json.loads((draft_dir / finish.OUTCOME_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _say(f"note: no {finish.OUTCOME_FILE} was written; the run's record is incomplete")
        return
    _say(
        f"committed to: {record.get('committed_to') or '(nothing committed)'}; "
        f"pushed={bool(record.get('pushed'))}; worktree_kept={bool(record.get('worktree_kept'))}"
    )
    for warning in record.get("warnings") or []:
        _say(f"  warning: {warning}")
        if "adopted the pull request" in str(warning):
            _say(
                f"  ^ the body this run wrote was NOT published. It is on disk at "
                f"{draft_dir / finish.PR_BODY_FILE}; paste it into that pull request "
                f"if it is the right one."
            )


# --- dispatch ---


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = (args.repo_root or Path.cwd()).resolve()
    data_dir = args.data_dir

    try:
        if args.command == "claim":
            _claim(args, repo_root, data_dir)
            return 0
        if args.command == "capture":
            _capture(args, repo_root, data_dir)
            return 0
        if args.command == "scaffold":
            _scaffold(args, repo_root, data_dir)
            return 0
        if args.command == "draft":
            report = _draft(args, repo_root, data_dir)
            return 0 if report.passed or report.stopped_because == "dry-run" else 1
        if args.command == "verify":
            verdict = _verify(args, repo_root, data_dir, args.adapter)
            return 0 if verdict.status is not verify.VerifyStatus.FAIL else 1
        if args.command == "finish":
            _finish(args, repo_root, data_dir, args.adapter)
            return 0
        if args.command == "run":
            return _run_everything(args, repo_root, data_dir)
    except Exception as exc:  # noqa: BLE001 -- every refusal is reported, never traced
        stage = stage_of(exc)
        if stage == "unknown":
            raise
        print(f"FAIL [{stage}] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_everything(args: argparse.Namespace, repo_root: Path, data_dir: Path) -> int:
    # FIRST, before the lease, the crawl and the reader round. `--dry-run` prints round
    # 0's prompt and spawns nothing, which `draft` can honour because the brief it
    # renders from is already on disk. On this chain the brief does not exist yet, and
    # building it costs a full crawl of the source and one real reader round -- so the
    # flag used to buy all of that, print the prompt, return without writing
    # workspace.json, and then exit 1 at `_verify` for the file it never wrote. Money
    # spent, no prompt-only run, and no way to get one.
    if args.dry_run:
        raise CliRefusal(
            "`--dry-run` prints round 0's prompt without spawning anything, and the "
            "prompt is rendered from a measured brief. `run` has no brief yet: building "
            "one crawls the whole source and buys a real reader round, so a dry run of "
            "this chain is not a dry run. Run `casesignal-adapter-draft claim "
            f"{args.candidate_id}` and `casesignal-adapter-draft capture "
            f"{args.candidate_id}` first, then `casesignal-adapter-draft draft "
            "<adapter> --dry-run`. Nothing has been touched and no lease was taken"
        )
    # Beside it, and for the same reason. `_draft` checks this too, but `_draft` runs
    # after `_capture` on this chain, so the ceiling that exists to stop an unattended
    # bill was itself only reached after the crawl and the paid reader round --
    # `run <cand> --rounds 500` spent before refusing. That is the exact defect class the
    # same commit hoisted the fixtures and scaffold refusals out of.
    loop.check_round_bounds(args.rounds, args.max_budget_usd)
    candidate, adapter_name = _claim(args, repo_root, data_dir)
    _capture(args, repo_root, data_dir, candidate=candidate)
    args.adapter = adapter_name
    _scaffold(args, repo_root, data_dir)
    _draft(args, repo_root, data_dir)
    verdict = _verify(args, repo_root, data_dir, adapter_name)
    if not args.finish:
        _say(
            "stopping before finish. `finish` commits, PUSHES and opens a pull request; "
            "re-run with --finish, or run "
            f"`casesignal-adapter-draft finish {adapter_name}` when the draft looks right."
        )
        return 0 if verdict.status is not verify.VerifyStatus.FAIL else 1
    if verdict.status is verify.VerifyStatus.FAIL:
        # The gate is on the CHAINED path only. `finish <adapter>` on its own stays
        # willing to ship a red draft, because an operator typing it has read the
        # verdict and may mean to open the pull request anyway for a human to
        # complete -- that is what PASS_WITH_TODOS and a titled FAIL are for. What
        # nobody asks for is a push they did not look at first: --finish was passed
        # before the verdict existed.
        _say(
            f"NOT finishing: the draft resolved {verdict.status.value}, and --finish "
            f"was asked for before that was known. `finish` commits, PUSHES and opens "
            f"a pull request. Read the verdict above; run "
            f"`casesignal-adapter-draft finish {adapter_name}` if you mean to ship a "
            f"red draft for a human to complete."
        )
        return 1
    _finish(args, repo_root, data_dir, adapter_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
