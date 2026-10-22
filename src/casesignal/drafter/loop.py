"""The parser pass, and the barrier that makes its green mean something.

Field identification cannot be made deterministic, so a *reader* agent supplied
the semantics up front: for each field, how to find it (``locators.json``) and
what one sampled record actually says (``expectations.json``). Those transcribed
values are the only independent statement of what a correct parser must produce.

Which is exactly why the pass that WRITES the parser must never see them. An
agent handed ``{"incident_date": "1998-04-02"}`` can satisfy a golden test by
returning that string, and the suite goes green over a parser that parses
nothing. So the arrangement here is:

* the expectation module lives OUTSIDE the worktree and is copied in only for
  the duration of one ``pytest`` invocation, then removed in a ``finally``;
* failures are fed back through :func:`redact`, which rebuilds each line out of
  its node id, the exception class name, and field names drawn from an
  allowlist -- record and field identity, never expected-versus-actual;
* the prompt is assembled from a WHITELIST of brief keys, because the brief's
  own ``fields`` block carries ``example`` values read off the source by the SP1
  classifier, and an example can coincide with a golden value.

The honest limit
----------------
Both files come from the SAME reader round. The barrier defends against the
parser agreeing with itself -- writing code to a value it was shown. It does
NOT defend against a reader that misidentified a field and then transcribed the
value it found under its own wrong reading: locator and expectation would agree,
the parser would satisfy both, and everything downstream would be green over a
field read out of the wrong column. Nothing in this module can see that. Only a
human comparing the memo against the source can.

What a round is
---------------
One ``client.run`` against the worktree, then one ``verify.run_pytest`` over the
generated invariant module plus the injected expectation module. The agent has
no Bash (see :mod:`casesignal.drafter.client`), so it cannot run the tests
itself: "green" is an exit code this loop observed, not a claim the model made
about its own work.

Rounds stop on the first green run; on the same failure signature twice, which
is a loop making no progress and buying another Opus round to prove it; on the
round budget; and on a round the wall clock killed.

Two conditions end the RUN rather than the round, because the worktree's status
is cumulative against HEAD and nothing commits there: a deleted file (every
later ``apply_back`` would raise ``DeletedInWorkspace`` anyway) and a write
outside the allowlist (likewise ``DisallowedWrite``). Retrying either just buys
rounds that cannot be applied.

A round that changed nothing is a FAILED round, not a quiet success. Files git
ignores are invisible to ``changed_paths``, so a round that wrote only into an
ignored path reports "no changes" -- and "no changes" read as success is the
same defect this package has already been bitten by once.

What this pass writes
---------------------
Both ``scrape.py`` and ``transform.py``. The scaffold leaves ``parse_records``,
``parse_detail`` and ``transform`` raising ``NotImplementedError``; a draft with
only the scrape written is an adapter that cannot load a row. No other brief in
this project assigns ``transform.py`` to anyone, and ``verify.find_todos``
already reads it.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casesignal.drafter import verify, workspace
from casesignal.drafter.client import ALLOWED_TOOLS, DEFAULT_MODEL, DrafterClient
from casesignal.drafter.inventory import to_adapter_field
from casesignal.drafter.reader import ExpectedRecord

__all__ = [
    "ADAPTER_PACKAGE_ROOT",
    "DEFAULT_PARSER_BUDGET_USD",
    "DEFAULT_ROUNDS",
    "DEFAULT_ROUND_TIMEOUT_S",
    "MAX_ROUNDS",
    "MAX_RUN_BUDGET_USD",
    "EXEMPLAR_JSON",
    "EXEMPLAR_NARRATIVE_HTML",
    "EXEMPLAR_STRUCTURED_HTML",
    "EXPECTATION_MODULE_NAME",
    "PARSER_MODULES",
    "PARSER_TOOLS",
    "RESERVED_SIGNATURES",
    "BarrierViolation",
    "LoopRefusal",
    "LoopReport",
    "RoundOutcome",
    "build_round_prompt",
    "choose_exemplar",
    "default_allowed_paths",
    "parser_module_paths",
    "parser_todos",
    "redact",
    "run_loop",
    # Re-exported deliberately, not incidentally: the loop's tests and the CLI
    # reach ``loop.verify.run_pytest`` and ``loop.workspace.Workspace`` by name,
    # and this package runs with implicit re-export off.
    "verify",
    "workspace",
]

# The name the expectation module takes while it is inside the worktree. Kept at
# the worktree root rather than under tests/ so the injection is one create and
# one unlink with no directory to reason about, and so a stray file by this name
# is trivially visible in `git status`.
EXPECTATION_MODULE_NAME = "test_expectations.py"

# The two modules this pass writes, relative to the adapter package.
PARSER_MODULES: tuple[str, ...] = ("scrape.py", "transform.py")

ADAPTER_PACKAGE_ROOT = "src/casesignal/etl/adapters"

# The parser needs to read the fixtures and the exemplar, and to write and edit
# its two modules. That is the whole of ALLOWED_TOOLS; the point of naming it
# again is that widening it here would be refused by the client, not silently
# honoured.
PARSER_TOOLS: tuple[str, ...] = ALLOWED_TOOLS

# Chosen deterministically by :func:`choose_exemplar`. All three are real,
# hand-written, in-tree adapters, so the agent reads working code rather than a
# description of working code.
EXEMPLAR_STRUCTURED_HTML = "cold_case_ar_asp"
EXEMPLAR_NARRATIVE_HTML = "cold_case_ok_osbi"
EXEMPLAR_JSON = "cold_case_nh_doj"

DEFAULT_ROUNDS = 3
DEFAULT_ROUND_TIMEOUT_S = 900

# Per round, not per run: three rounds at this ceiling is the run's bound. There
# is no --max-turns in the CLI this package targets, so without a dollar figure
# the wall clock is the only thing standing between a wedged round and an
# unattended bill. ``client.run`` defaults it to None, and an opt-in nobody
# exercises is not a ceiling, so it is passed on every call from here.
DEFAULT_PARSER_BUDGET_USD = 5.0

# And the ceiling the per-round budget does not provide. ``--rounds`` is an
# operator-typed integer with nothing between a typo and the bill: ``--rounds 30`` for
# ``--rounds 3`` is thirty unattended agent sessions, and because the budget is per
# round the only other bound -- the wall clock -- scales with it rather than against it.
# So the run gets two bounds of its own: how many rounds it may take at all, and what
# the whole run may cost at the ceiling it was handed.
#
# Both numbers are choices rather than measurements. Ten rounds is well past the point
# where a loop that is going to converge has; sixty dollars is a session an operator
# would want to have decided on deliberately. Neither is a safety property -- an
# operator who means it re-runs `draft` -- which is why they refuse with a message that
# says what to do rather than silently clamping.
MAX_ROUNDS = 10
MAX_RUN_BUDGET_USD = 60.0

# The brief keys :func:`build_round_prompt` may render. A WHITELIST rather than a
# denylist, and the difference is load-bearing: brief["fields"][name]["example"]
# holds a value the SP1 classifier read off the source, which can be the same
# string a golden test expects. Rendering the brief wholesale would walk the
# expected values straight into the prompt through a key nobody was thinking
# about. Anything not named here never reaches the agent.
#
# The rule for adding to this list: every entry describes the SOURCE, never one
# of its records. URLs, shapes, counts, pagination, fixture filenames and the
# case-type vocabulary are all statements about how the source is built. A token
# from that vocabulary can coincide with a transcribed value -- an expected
# case_type of "homicide" against a case_type_mix listing "homicide" -- and that
# is accepted rather than scrubbed, because it says what words the source uses
# and not which record carries which. A key holding per-record data says exactly
# that, and does not belong here.
#
# One entry holds by cooperation rather than by construction, and is called out
# so nobody reads the rule above as stronger than it is. ``detail_url_pattern``
# is free-form LLM output from the classifier, validated only as
# ``{"type": ["string", "null"]}`` (scout/classify.py) -- every documented example
# is a ``{id}`` template, but a classifier that wrote a concrete URL would render
# a real source_case_id into the prompt, and source_case_id is a REQUIRED_FIELDS
# expectation. Every other entry is either derived by capture code or is a fixed
# vocabulary.
_PROMPT_BRIEF_KEYS: tuple[str, ...] = (
    "adapter_name",
    "source_key",
    "state",
    "index_url",
    "channel",
    "page_type",
    "shape",
    "transport",
    "fixtures_root",
    "listing_pages",
    "pagination_kind",
    "pagination_detail",
    "detail_url_pattern",
    "dataset_id",
    "source_id_strategy",
    "source_id_field",
    "records_captured",
    "records_total",
    "listing_record_count",
    "truncated",
    "case_type_mix",
)

# Rendered by :func:`_fixture_lines` rather than by the generic loop, because they
# are lists and read as an itemised block. They are part of the same whitelist and
# bound by the same rule: a fixture name is counter-derived
# (``shapes/fixtures.py:fixture_name``, deliberately never built from anything the
# server supplied), so it describes the capture and cannot carry source data. That
# is a CROSS-MODULE invariant, so it is pinned by
# test_fixture_names_cannot_carry_anything_the_server_supplied rather than trusted.
_PROMPT_FIXTURE_KEYS: tuple[str, ...] = ("listing_paths", "detail_paths")

# A pytest short-summary line: the verdict word, the node id, then free text this
# module never copies.
_NODE_LINE = re.compile(r"^(?P<head>FAILED|ERROR)\s+(?P<node>\S+)(?P<rest>.*)$", re.DOTALL)

# The exception class name pytest prints after the node id. It is one of the
# three things :func:`redact` carries over from the raw line -- the others are
# the verdict word and the node id with its parameters stripped -- and the
# pattern bounds what it can be: a dotted identifier at a fixed position,
# stopping at the colon that introduces the message. The message body itself is
# unreachable through it.
_KIND = re.compile(r"^\s*-\s*(?P<kind>[A-Za-z_][A-Za-z0-9_.]*)\b")

# A parametrised node id's bracketed payload. pytest builds it out of the
# parameter VALUES, so it is the one part of a node id that is free text rather
# than a generated name -- ``test_field[OSBI-77-0142]`` is a record id in an
# identifier. Today's generated modules are all plain ``def test_*``, so nothing
# in tree produces one; ``redact`` is a public primitive that Tasks 14 and 15
# bind to, and one natural refactor (a golden test per record per FIELD,
# parametrised) walks straight into it. Substituted for a constant of our own
# rather than left to the value scan, which cannot see an untranscribed record.
_PARAM = re.compile(r"\[[^\]]*\]")

# Identifier-shaped tokens in the assertion message, used ONLY to look up an
# allowlist. See :func:`_fields_named` for why nothing matched here is ever
# copied into the output.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Below this length a "value" cannot be leaked through a node id in any way a
# reader could decode, while it CAN collide with one constantly -- an expected
# age of "17" would blank every node whose fixture index contains 17, redacting
# the field identity the feedback exists to carry. The whitelist construction is
# the barrier; this scan is the second line behind it.
_MIN_LEAKABLE = 3

# What the scaffold names the golden module in the repository
# (``scaffold.scaffold`` writes ``tests/unit/etl/adapters/test_<adapter>_expectations.py``).
# Matched by basename anywhere in the worktree, because the harm is the file's
# presence and not its directory.
#
# No underscore before ``expectations``, so this also matches
# :data:`EXPECTATION_MODULE_NAME` -- the name this loop itself injects under. An
# untracked file by that name is caught by the dirty-worktree guard at no spend,
# but a COMMITTED one is invisible to that guard and would otherwise be read by
# the agent for a whole round before ``_run_tests`` refused it. It is the one
# filename this check most obviously has to cover.
_GOLDEN_MODULE_GLOB = "test_*expectations.py"

# The dict the generated expectation module binds its transcribed values to.
# Read back out of the module by :func:`_expectations_from_module` so the value
# scan works even when a caller passes no expectations.
_GOLDEN_LITERAL = "EXPECTATIONS"

# The ``RoundOutcome.signature`` values that name a condition rather than a set of
# failing tests. In every one of them the tests did not run, so a consumer that
# reads a signature as "which tests were red" is wrong about exactly these four.
RESERVED_SIGNATURES: tuple[str, ...] = (
    "no-changes",
    "deleted-in-workspace",
    "unsupported-entry",
    "wrote-outside-allowlist",
)

# Indirected so a test can drive the round clock without patching stdlib ``time``
# out from under pytest itself.
_now = time.monotonic


class LoopRefusal(ValueError):
    """Raised for a loop invocation this module refuses to start.

    A refusal, not a failed run: nothing has been spawned and nothing billed, so
    the caller can fix the call and try again.
    """


class BarrierViolation(LoopRefusal):
    """Raised when a path in the call would put the golden values inside the worktree.

    Its own class because it is not a wiring mistake like the others. Every other
    refusal here costs a re-run; this one, unnoticed, costs the meaning of every
    green result the pipeline has ever printed.
    """


@dataclass(frozen=True)
class RoundOutcome:
    """One round: what it was, whether the tests passed, and how it failed.

    ``signature`` is the redacted failure set joined into one string, EXCEPT for
    four reserved values that name a condition instead of a failure set, because
    in each of them no test was run at all: ``"no-changes"``, and the three
    run-ending ones ``"deleted-in-workspace"``, ``"unsupported-entry"`` and
    ``"wrote-outside-allowlist"``. A consumer branching on the signature -- which
    is what the finishing task must do to attribute a refusal -- has to know that,
    so the reserved names are listed in :data:`RESERVED_SIGNATURES` rather than
    left to be recognised by eye.

    Two consecutive identical signatures mean the round changed nothing a test
    could see, which is the loop's only evidence of an agent going in circles.
    """

    index: int
    passed: bool
    signature: str
    timed_out: bool


@dataclass(frozen=True)
class LoopReport:
    """Every round that ran, and why the loop stopped.

    ``passed`` is the LAST round's verdict and not "any round passed": the
    worktree carries forward, so a green round followed by a red one is a red
    draft.
    """

    rounds: list[RoundOutcome]
    passed: bool
    stopped_because: str


# --- vocabulary and layout ---


def parser_module_paths(root: Path, adapter_name: str) -> list[Path]:
    """The modules the parser pass writes, under ``root``.

    Exposed because ``verify.find_todos`` reads ONE path, and the pass leaves
    marked TODOs in either module. A caller that scans only ``transform.py``
    silently drops every claim the agent made in ``scrape.py``, and a dropped
    claim resolves to PASS.
    """
    package = root / ADAPTER_PACKAGE_ROOT / adapter_name
    return [package / name for name in PARSER_MODULES]


def parser_todos(root: Path, adapter_name: str) -> list[verify.Todo]:
    """Marked TODOs across both parser modules, tolerating a module not yet written.

    For the per-round record only. Rounds 0 and 1 legitimately run before both
    modules exist, so a missing file is skipped here rather than raised. The
    verification pass must NOT use this: ``verify.find_todos`` raises
    ``TransformNotDrafted`` on a missing module precisely so "no TODOs found"
    cannot be confused with "there is no parser", and that refusal is the point
    of the call at that stage. Task 15 calls ``find_todos`` over
    :func:`parser_module_paths` directly.
    """
    todos: list[verify.Todo] = []
    for path in parser_module_paths(root, adapter_name):
        try:
            todos.extend(verify.find_todos(path))
        except verify.TransformNotDrafted:
            continue
    return todos


def default_allowed_paths(brief: Mapping[str, Any]) -> list[str]:
    """The one prefix the parser pass may write under: its own adapter package.

    Deliberately excludes the generated test modules. A pass that could edit the
    tests it is being graded by is not being graded.
    """
    return [f"{ADAPTER_PACKAGE_ROOT}/{brief['adapter_name']}"]


def choose_exemplar(brief: Mapping[str, Any]) -> str:
    """Which in-tree adapter this draft should be modelled on.

    Three real shapes, three real adapters, decided from the capture rather than
    from anyone's taste:

    * a JSON payload -- Socrata, ArcGIS, or JSON embedded in a page -- reads
      records off a decoded object, which is what ``cold_case_nh_doj`` does;
    * HTML whose fields have their own CSS selectors is structured extraction,
      which is ``cold_case_ar_asp``;
    * everything else is narrative HTML, which is ``cold_case_ok_osbi``.

    The last is the default, and that is the conservative direction: a brief
    whose reader could not name a per-field selector is describing a source
    whose fields are not in their own elements, which IS the narrative case.
    """
    shape = str(brief.get("shape") or "")
    kinds = [str(entry.get("kind") or "") for entry in _locators(brief).values()]
    if shape in {"socrata", "arcgis", "embedded_json"} or kinds.count("json_path") > len(kinds) / 2:
        return EXEMPLAR_JSON
    if kinds.count("css") > kinds.count("label"):
        return EXEMPLAR_STRUCTURED_HTML
    return EXEMPLAR_NARRATIVE_HTML


def _locators(brief: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = brief.get("locators") or {}
    if not isinstance(raw, Mapping):
        return {}
    return {str(name): entry for name, entry in raw.items() if isinstance(entry, Mapping)}


# --- redaction ---


def redact(failures: Sequence[str], expectations: Sequence[ExpectedRecord]) -> list[str]:
    """Rewrite pytest failures as record-and-field identity, and nothing else.

    Built by CONSTRUCTION, not by substitution. Each line is rebuilt from three
    things taken off the raw line -- the verdict word, the node id with every
    bracketed parameter replaced by a constant, and the exception class name --
    plus field names selected from an allowlist. The assertion MESSAGE is never
    carried over: an unanticipated formatting of an assertion, a custom
    ``__repr__``, a diff pytest chose to render sideways, none of them can leak a
    value through a path this function never travels. Search-and-replace would
    have to anticipate every one of those shapes and would fail open on the first
    it did not.

    Each of the three is bounded by its own pattern rather than by trust:
    :data:`_NODE_LINE` admits two verdict words, :data:`_PARAM` removes the only
    free-text part of a node id, and :data:`_KIND` admits a dotted identifier at a
    fixed position. What is left of a node id is a generated test name and a path
    this loop itself chose.

    That bounding matters because the scan below cannot substitute for it: the
    scan knows only the SAMPLED records, and both a parametrised node id and an
    assertion message quote whatever record actually failed, which is usually one
    nobody transcribed.

    ``expectations`` is read for two things, neither of them a value that reaches
    the output. Its VALUES become the scan that runs AFTER the reconstruction:
    node ids are generated from fixture names and indices, but a parametrised
    test could in principle carry a value in its id, so the result is checked and
    downgraded to the file name -- and then, if that still carries a value,
    withheld entirely. Values shorter than three characters are not scanned; see
    :data:`_MIN_LEAKABLE`.

    Its KEYS become the field allowlist. The generated golden test is one test
    per RECORD, so the node id names the record and the FIELD name appears only
    in the assertion message -- and "expectation 2, incident_date, mismatch"
    without the field name is feedback an agent cannot act on. So the message is
    scanned for identifier-shaped tokens, each is looked up in the allowlist, and
    the ALLOWLIST's spelling is what gets written out. No byte of the message is
    copied; a token that is not already a known field name cannot appear.

    The field allowlist covers both vocabularies. The reader writes ``age`` and
    ``victim_name`` while the generated tests were remapped to ``victim_age`` and
    ``case_name``, so every key is admitted under both spellings.
    """
    values = _expected_values(expectations)
    names = _expected_field_names(expectations)
    return [_redact_one(line, values, names) for line in failures]


def _expected_field_names(expectations: Sequence[ExpectedRecord]) -> dict[str, str]:
    """Case-folded token to the spelling this module will emit for it."""
    names: dict[str, str] = {}
    for record in expectations:
        raw = _values_of(record)
        if raw is None:
            continue
        for key in raw:
            for spelling in sorted({str(key), to_adapter_field(str(key))}):
                names.setdefault(spelling.casefold(), spelling)
    return names


def _fields_named(rest: str, names: Mapping[str, str]) -> list[str]:
    """The known field names this message mentions, in first-seen order.

    Emits ``names[token]`` and never ``token``: the output is assembled from the
    allowlist, so the message can only ever SELECT from a set of field names, not
    contribute to it.
    """
    found: list[str] = []
    for word in _WORD.findall(rest):
        canonical = names.get(word.casefold())
        if canonical is not None and canonical not in found:
            found.append(canonical)
    return found


def _values_of(record: object) -> Mapping[str, object] | None:
    raw = record.get("values") if isinstance(record, Mapping) else getattr(record, "values", None)
    return raw if isinstance(raw, Mapping) else None


def _expected_values(expectations: Sequence[ExpectedRecord]) -> frozenset[str]:
    """Every transcribed value, whitespace-collapsed and case-folded, worth scanning for."""
    found: set[str] = set()
    for record in expectations:
        raw = _values_of(record)
        if raw is None:
            continue
        for value in raw.values():
            text = " ".join(str(value).split())
            if len(text) >= _MIN_LEAKABLE:
                found.add(text.casefold())
    return frozenset(found)


def _leaks(text: str, values: frozenset[str]) -> bool:
    folded = " ".join(text.split()).casefold()
    return any(value in folded for value in values)


def _redact_one(line: str, values: frozenset[str], names: Mapping[str, str]) -> str:
    match = _NODE_LINE.match(line.strip())
    if match is None:
        # Not a node line: one of verify's own diagnoses ("pytest exited 5 (no
        # tests collected)"). Those carry no golden value and are the most useful
        # thing the agent can be told when nothing ran at all, so they survive --
        # subject to the same scan as everything else.
        return line.strip() if not _leaks(line, values) else _WITHHELD_DIAGNOSTIC

    head = match.group("head")
    # The bracketed payload of a parametrised id is the one part of a node id
    # pytest builds out of free text, so it is replaced with a constant of ours
    # rather than trusted to the scan below. See :data:`_PARAM`.
    node = _PARAM.sub("[...]", match.group("node"))
    kind_match = _KIND.match(match.group("rest"))
    kind = kind_match.group("kind") if kind_match else ""
    label = "mismatch" if kind in {"", "AssertionError"} else kind
    fields = _fields_named(match.group("rest"), names)
    suffix = f" [{', '.join(fields)}]" if fields else ""

    text = f"{head} {node} - {label}{suffix}"
    if not _leaks(text, values):
        return text
    text = (
        f"{head} {node.split('::', 1)[0]} - {label}{suffix} "
        f"(node name withheld: it carried an expected value)"
    )
    if not _leaks(text, values):
        return text
    return f"{head} <withheld: the failure identity carried an expected value>"


_WITHHELD_DIAGNOSTIC = "<a diagnostic line was withheld because it carried an expected value>"


# --- the prompt ---


def build_round_prompt(
    brief: Mapping[str, Any],
    exemplar: str,
    failures: Sequence[str],
) -> str:
    """The parser pass's whole instruction for one round.

    ``failures`` must already be through :func:`redact`. Nothing here re-reads
    the brief's ``fields`` block or any other key outside
    :data:`_PROMPT_BRIEF_KEYS`.
    """
    adapter = str(brief.get("adapter_name") or "the adapter")
    package = f"{ADAPTER_PACKAGE_ROOT}/{adapter}"
    memo = f"docs/drafts/{adapter}.md"
    invariants = f"tests/unit/etl/adapters/test_{adapter}_invariants.py"

    return "\n".join(
        [
            _prompt_head(adapter, package, memo, invariants, exemplar),
            _prompt_capture(brief),
            _prompt_fields(brief),
            _PROMPT_RULES,
            _prompt_feedback(failures),
        ]
    )


def _prompt_head(adapter: str, package: str, memo: str, invariants: str, exemplar: str) -> str:
    return f"""You are writing the parser for a cold-case source adapter that has already
been captured, measured and scaffolded. You are working inside a throwaway git
worktree. You have no shell: you cannot run the tests, and you are not being
asked to. Write the parser; this harness runs the tests and judges the result.

Adapter: {adapter}
Package: {package}/
Design memo (READ THIS FIRST): {memo}
Generated invariant tests (read, never edit): {invariants}
Model your work on this hand-written, working, in-tree adapter: \
{ADAPTER_PACKAGE_ROOT}/{exemplar}/

Write exactly two modules, both under {package}/:

  scrape.py     Pure parsing. Given fetched text (HTML or a decoded payload),
                return one dict per record in DOCUMENT ORDER. No HTTP, no
                database, no side effects. Document order is load-bearing: the
                golden tests address records as "<fixture>#<index>" derived from
                the same walk the capture made, so a parse that reorders,
                filters or dedupes records invalidates every one of them.

  transform.py  Define to_case(record), a pure mapping returning case_name,
                source_case_id, case_type and ISO incident_date (when present).
                Define transform(context), the real persistence stage, calling
                to_case for each raw record. No pass or NotImplementedError.
                The transform stage: raw rows to canonical cold-case rows,
                modelled on the exemplar's transform.py. The scaffold left it
                raising NotImplementedError, which means the drafted adapter
                cannot load a single row until you write it.

Then wire adapter.py to them: parse_records and parse_detail should delegate to
scrape.py, and the adapter's transform method to transform.py. adapter.py is
generated but yours to edit; the two test modules are not."""


def _prompt_capture(brief: Mapping[str, Any]) -> str:
    lines = [f"  {key}: {brief[key]!r}" for key in _PROMPT_BRIEF_KEYS if key in brief]
    fixtures = _fixture_lines(brief)
    return "\n".join(["\n=== What the capture found ===\n", *lines, *fixtures])


def _fixture_lines(brief: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("listing_paths", "detail_paths"):
        paths = brief.get(key) or []
        if not isinstance(paths, Sequence) or isinstance(paths, str):
            continue
        lines.append(f"  {key}:")
        lines.extend(f"    - {path}" for path in paths)
    return lines


def _prompt_fields(brief: Mapping[str, Any]) -> str:
    """The measured fields and how the reader said to find them.

    Locator VALUES are selectors, on-page label literals and JSON paths -- the
    address of a value, never the value. That is what makes this block safe to
    render, and it is the reason the field inventory's ``example`` entries are
    not rendered beside it.
    """
    floors = brief.get("floors") or {}
    locators = _locators(brief)
    names = sorted(set(floors) | set(locators))
    if not names:
        return "\n=== Fields ===\n\n  (the brief names no measured fields)"

    rows: list[str] = []
    for name in names:
        entry = locators.get(name, {})
        kind = entry.get("kind", "?")
        value = entry.get("value", "?")
        page = entry.get("page", "?")
        floor = floors.get(name)
        floor_text = "no floor" if floor is None else f"floor {float(floor):.2f}"
        rows.append(f"  {name:<18} {floor_text:<12} [{page}] {kind}: {value!r}")

    return "\n".join(
        [
            "\n=== Fields to extract (adapter vocabulary) ===\n",
            "These are the raw keys the adapter carries, the coverage floor each",
            "must clear across the captured records, and how the reader said to",
            "find each one. A locator is an address, not an answer: verify it",
            "against the fixtures rather than trusting it, and prefer your own",
            "reading of the markup where the two disagree.\n",
            *rows,
        ]
    )


_PROMPT_RULES = """
=== Rules ===

1. Extract a field as None when the record does not carry it. Never "". The
   coverage floors were measured by counting records that carry a value, and an
   empty string counts as a value to some readers and not to others.

2. Where a field genuinely cannot be extracted from what the source publishes,
   leave a marked TODO on the line that would have done it, in exactly this
   form, a lowercase field name in parentheses followed by a colon:

       # TODO(county): the listing prints no county and there is no detail page

   That marker is machine-read and graded per field: on a required field it
   fails the draft, on an optional one it is reported as unresolved work. A bare
   "TODO" is invisible to it. Do NOT restate this convention in prose, in a
   docstring or in a comment that is not itself a real claim about a real field
   -- the reader of these files matches the form, not the intent, so an
   illustration of the convention is counted as a TODO against whatever field it
   names.

3. Write ONLY inside the adapter package. A write anywhere else ends the run.
   Do not create symlinks. Do not edit the generated test modules.

4. There is a second test module, holding values a different agent transcribed
   off these same fixtures, and you cannot see it. That is deliberate and it is
   not an obstacle to work around: it is the only reason a green result here
   means the parser works rather than that it agreed with itself. Do not go
   looking for it, and do not hardcode a value to satisfy a failing test. A
   parser that special-cases a record is worth less than one that fails honestly
   on it.

5. Failure feedback names the record and the field only, never the expected
   value. That is the same rule from the same reason. If a field keeps failing,
   re-read the fixture and the memo -- the answer is in the source, which you
   can see all of."""


def _prompt_feedback(failures: Sequence[str]) -> str:
    if not failures:
        return """
=== Previous rounds ===

This is the first round. Nothing has been run yet."""
    listed = "\n".join(f"  {line}" for line in failures)
    return f"""
=== What failed last round ===

Each line names a test and how it failed. Expected and actual values are
withheld by design; see rule 5.

{listed}"""


# --- the loop ---


def run_loop(
    *,
    ws: workspace.Workspace,
    client: DrafterClient,
    brief: Mapping[str, Any],
    exemplar: str,
    expectation_module: Path,
    test_paths: Sequence[Path],
    rounds: int = DEFAULT_ROUNDS,
    timeout_s: int = DEFAULT_ROUND_TIMEOUT_S,
    artifacts_dir: Path,
    expectations: Sequence[ExpectedRecord] | None = None,
    allowed_paths: Sequence[str] | None = None,
    model: str = DEFAULT_MODEL,
    max_budget_usd: float | None = DEFAULT_PARSER_BUDGET_USD,
    dry_run: bool = False,
) -> LoopReport:
    """Draft the parser, round by round, and report what happened.

    ``expectation_module`` and ``artifacts_dir`` must both sit OUTSIDE ``ws.path``
    and that is checked, not documented: the module is the golden values and the
    artifacts hold raw pytest output that quotes them. Either one inside the
    worktree is readable by the drafting agent for the whole run, which is the
    barrier gone.

    ``test_paths`` are the generated modules to run, relative to the worktree.
    The expectation module is appended by this function under
    :data:`EXPECTATION_MODULE_NAME` and is not named here. An empty sequence is
    refused: ``pytest`` with no path falls back to the ``testpaths`` setting,
    which would run the entire repository suite inside a drafting round.

    ``dry_run`` assembles and persists round 0's prompt and returns without
    spawning anything, so an operator can read what the agent would be told.
    """
    allowed = list(allowed_paths) if allowed_paths is not None else default_allowed_paths(brief)
    golden = list(expectations) if expectations is not None else _expectations_from(brief)
    paths = _checked_paths(ws, expectation_module, test_paths, artifacts_dir)
    if not golden:
        # Read the values back out of the module about to be injected. Without
        # this the scan is off by default, which is survivable for redact (the
        # reconstruction is primary) but not for the in-tree check below, whose
        # whole job is to notice a copy of these values already in the tree.
        golden = _expectations_from_module(expectation_module)
    _refuse_golden_values_already_in_the_worktree(ws, brief, golden)
    check_round_bounds(rounds, max_budget_usd)
    if timeout_s <= 0:
        raise LoopRefusal(f"timeout_s must be positive, got {timeout_s}")

    _refuse_a_dirty_worktree(ws, allowed)
    _refuse_a_redirected_destination(ws, allowed)

    failures: list[str] = []
    outcomes: list[RoundOutcome] = []
    previous_signature: str | None = None
    stopped = "budget"

    for index in range(rounds):
        round_dir = artifacts_dir / f"{index:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        prompt = build_round_prompt(brief=brief, exemplar=exemplar, failures=failures)
        (round_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        if dry_run:
            return LoopReport(rounds=[], passed=False, stopped_because="dry-run")

        started = _now()
        result = client.run(
            prompt,
            allowed_tools=PARSER_TOOLS,
            model=model,
            cwd=ws.path,
            timeout_s=timeout_s,
            max_budget_usd=max_budget_usd,
        )
        elapsed = _now() - started
        # Measured, not parsed out of the client's message: a round that used its
        # whole budget and came back unsuccessful was killed by the clock,
        # whatever wording the client chose for saying so.
        timed_out = not result.ok and elapsed >= timeout_s

        changed = workspace.changed_paths(ws)
        fatal = _fatal_condition(ws, changed, allowed)
        if fatal is not None:
            outcomes.append(RoundOutcome(index, False, fatal, timed_out))
            _persist(round_dir, None, result.text, changed, [], fatal, elapsed, brief, ws)
            stopped = fatal
            break

        if not changed:
            # Not a quiet success. Ignored paths are invisible to changed_paths,
            # so a round that wrote only into one looks exactly like this.
            signature = "no-changes"
            outcomes.append(RoundOutcome(index, False, signature, timed_out))
            # No feedback list: the previous round's failures are not this
            # round's, and no test ran here to produce any of its own.
            _persist(round_dir, None, result.text, changed, [], signature, elapsed, brief, ws)
        else:
            outcome = _run_tests(ws, expectation_module, paths, timeout_s)
            failures = redact(outcome.failures, golden)
            signature = "|".join(sorted(failures))
            outcomes.append(RoundOutcome(index, outcome.passed, signature, timed_out))
            _persist(
                round_dir, outcome, result.text, changed, failures, signature, elapsed, brief, ws
            )
            if outcome.passed:
                stopped = "green"
                break

        if signature == previous_signature:
            stopped = "no-progress"
            break
        if timed_out:
            stopped = "timeout"
            break
        previous_signature = signature

    return LoopReport(
        rounds=outcomes,
        passed=bool(outcomes) and outcomes[-1].passed,
        stopped_because=stopped,
    )


def check_round_bounds(rounds: int, max_budget_usd: float | None) -> None:
    """Refuse a run whose size nobody meant, before anything is cut or spent.

    Called from :func:`run_loop`, so the API path is bound, and again from the CLI
    before the lease and the worktree, so an operator's typo does not cost a cleanup.
    Exposed for exactly that second caller: a bound only enforced after a worktree
    exists is a bound that charges for finding the typo.
    """
    if rounds < 1:
        raise LoopRefusal(f"rounds must be at least 1, got {rounds}")
    if rounds > MAX_ROUNDS:
        raise LoopRefusal(
            f"rounds={rounds} is over the run ceiling of {MAX_ROUNDS}. Every round is a "
            f"real unattended agent session and --max-budget-usd bounds one round, not "
            f"the run, so nothing else here stands between a mistyped digit and "
            f"{rounds} of them. If you mean it, run `draft` again when the first "
            f"{MAX_ROUNDS} are spent -- it resumes the same worktree"
        )
    if max_budget_usd is not None and rounds * max_budget_usd > MAX_RUN_BUDGET_USD:
        raise LoopRefusal(
            f"{rounds} round(s) at ${max_budget_usd:g} each is ${rounds * max_budget_usd:g} "
            f"for one unattended run, over the ${MAX_RUN_BUDGET_USD:g} run ceiling. Lower "
            f"--rounds or --max-budget-usd; a session this size is one to decide on "
            f"deliberately rather than to discover afterwards"
        )


def _checked_paths(
    ws: workspace.Workspace,
    expectation_module: Path,
    test_paths: Sequence[Path],
    artifacts_dir: Path,
) -> list[Path]:
    """Refuse every call shape that would put golden values where the agent can read them."""
    tree = ws.path.resolve()
    if _inside(expectation_module, tree):
        raise BarrierViolation(
            f"expectation_module {expectation_module} is inside the worktree {ws.path}. It "
            f"holds the transcribed values the parser pass is graded against; from inside "
            f"the tree the agent can simply read them and satisfy every golden test by "
            f"hardcoding. It must live in the main checkout and be injected per run"
        )
    if _inside(artifacts_dir, tree):
        raise BarrierViolation(
            f"artifacts_dir {artifacts_dir} is inside the worktree {ws.path}. Every round "
            f"writes raw pytest output there, and raw output quotes the expected values "
            f"verbatim"
        )
    if not test_paths:
        raise verify.NoTestPaths(
            "run_loop was given no test paths. pytest with no path argument falls back to "
            "the `testpaths` setting, so the drafting round would collect and run the "
            "entire repository suite"
        )

    checked: list[Path] = []
    for path in test_paths:
        resolved = (tree / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if not _inside(resolved, tree):
            raise BarrierViolation(
                f"test path {path} resolves to {resolved}, outside the worktree {ws.path}. "
                f"Running a module from the main checkout inside the loop is how the "
                f"expectation module gets read without ever being injected"
            )
        if resolved.name == EXPECTATION_MODULE_NAME:
            raise BarrierViolation(
                f"test path {path} names {EXPECTATION_MODULE_NAME}, which run_loop injects "
                f"and removes itself. A caller naming it is a caller that has already "
                f"placed it in the tree"
            )
        if not resolved.is_file():
            raise LoopRefusal(
                f"test path {path} does not exist in the worktree ({resolved}). The "
                f"scaffolded modules must be staged there before drafting, or every round "
                f"is bought and then graded by a pytest usage error"
            )
        checked.append(Path(path))
    return checked


def _refuse_golden_values_already_in_the_worktree(
    ws: workspace.Workspace, brief: Mapping[str, Any], golden: Sequence[ExpectedRecord]
) -> None:
    """Refuse a worktree that already contains this adapter's transcribed values.

    Every other barrier check asks about a PATH the caller handed in. None of them
    asks the question that matters most: is a copy of the golden values already
    sitting in the tree under the name the scaffold gives it? The scaffold writes
    ``tests/unit/etl/adapters/test_<adapter>_expectations.py`` into the repository,
    so once a draft has been merged, EVERY later worktree cut from HEAD contains
    it -- and it is a tracked, committed file, so the dirty-worktree guard cannot
    see it either. The reachable case is not operator error, it is a RE-DRAFT, and
    the failure is silent: the round runs green while the agent could have read
    the answers with one glob.

    Two checks, and NOT a blanket refusal of every match. A blanket glob would
    refuse the second adapter this pipeline ever drafts, because the first one's
    module is in the tree by then, and a refusal an operator cannot clear is a
    pipeline that stops. So:

    * the module named after THIS adapter is refused wherever it appears, because
      its values grade this draft and nothing else explains its presence;
    * any other match is refused only if it CONTAINS one of this run's transcribed
      values, which catches the same module under a stale name after a rename, and
      leaves a sibling adapter's module -- whose values grade a different source --
      alone.

    Start-of-run only. The agent cannot introduce one: a write outside the
    allowlist ends the run on the next round, and a write inside it can only
    contain values the agent did not have.
    """
    adapter = str(brief.get("adapter_name") or "")
    own = f"test_{adapter}_expectations.py" if adapter else None
    values = _expected_values(golden)

    for path in sorted(ws.path.rglob(_GOLDEN_MODULE_GLOB)):
        if not path.is_file():
            continue
        relative = path.relative_to(ws.path)
        if path.name == EXPECTATION_MODULE_NAME:
            raise BarrierViolation(
                f"the worktree {ws.path} already contains {relative}. That is the name this "
                f"loop injects the golden module under, so nothing legitimate holds it; "
                f"committed, it is invisible to the dirty-worktree guard and the parser pass "
                f"would read it for a whole round before the pre-injection check refused it"
            )
        if own is not None and path.name == own:
            raise BarrierViolation(
                f"the worktree {ws.path} already contains {relative}, which is the golden "
                f"module for {adapter}: a previous draft of this adapter was merged, and "
                f"this worktree was cut from a commit carrying it. The parser pass can read "
                f"the transcribed values straight out of it and satisfy every golden test by "
                f"hardcoding, so every green result from this run would mean nothing. Draft "
                f"from a branch that does not carry it, or move it aside deliberately"
            )
        if values and _leaks(_read_or_empty(path), values):
            raise BarrierViolation(
                f"the worktree {ws.path} already contains {relative}, and it carries values "
                f"this run transcribed for {adapter or 'this adapter'} -- most likely the "
                f"same module under an adapter name that has since changed. It is readable "
                f"by the parser pass for the whole run"
            )


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Unreadable is not "clean": fall through to the name check having proved
        # nothing, rather than raising over a permissions problem in some
        # unrelated corner of a full repository checkout.
        return ""


def _expectations_from_module(path: Path) -> list[ExpectedRecord]:
    """The transcribed values bound to ``EXPECTATIONS`` in a generated golden module.

    Parsed, never imported: importing it would run a generated module in this
    process, and ``ast.literal_eval`` over the assignment's right-hand side reads
    a dict literal without evaluating anything. Returns ``[]`` for any module this
    cannot read that way -- a hand-written expectation module, a shape the
    generator has since changed -- because this is a best-effort default behind an
    explicit ``expectations`` argument, not a parser anything depends on.
    """
    try:
        tree = ast.parse(_read_or_empty(path))
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets: list[ast.expr] = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == _GOLDEN_LITERAL for t in targets):
            continue
        if node.value is None:
            continue
        try:
            literal = ast.literal_eval(node.value)
        except ValueError:
            return []
        if not isinstance(literal, Mapping):
            return []
        return [
            ExpectedRecord(record_key=str(key), values={str(k): str(v) for k, v in row.items()})
            for key, row in literal.items()
            if isinstance(row, Mapping)
        ]
    return []


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return resolved == root or root in resolved.parents


def _refuse_a_dirty_worktree(ws: workspace.Workspace, allowed: Sequence[str]) -> None:
    """Refuse to start over changes outside the allowlist that are already there.

    The worktree's status is cumulative and nothing commits there, so anything
    dirty at the start is dirty at the end -- and ``apply_back`` refuses the whole
    round for it. Saying so before the first round is bought is the only cheap
    moment. Dirt INSIDE the allowlist is expected: the scaffold put it there.
    """
    stray = workspace.stray_writes(workspace.changed_paths(ws), allowed)
    if stray:
        raise LoopRefusal(
            f"the worktree {ws.path} already carries changes outside the paths this draft "
            f"may write ({', '.join(allowed)}): {', '.join(stray)}. Worktree status is "
            f"cumulative, so apply_back would refuse the finished draft for changes no "
            f"round of it made"
        )


def _refuse_a_redirected_destination(ws: workspace.Workspace, allowed: Sequence[str]) -> None:
    """Refuse a repository whose allowlist prefix is reached through a symlink.

    ``apply_back`` refuses the whole round when any component of a destination path
    is a symlink, because ``shutil.copy2`` writes THROUGH a link at the destination
    and that is an allowlist bypass. Nothing about that depends on the round: it is
    a fact about the operator's checkout, and it is constant.

    Constancy is the reason to check it HERE and not per round. Measured: with a
    symlinked component at the allowlist prefix, the loop otherwise runs its full
    three rounds and stops on ``"budget"``, and only then does ``apply_back`` raise
    -- the entire spend on a draft that could never come home. That is the same
    loss :func:`_refuse_a_dirty_worktree` exists to prevent, and it runs on the
    same reasoning: a condition that cannot change is a condition worth naming
    before a dollar is spent.

    The allowlist prefixes are what is checked, rather than any changed path,
    because a symlink at or above the prefix is what makes the condition constant
    in the first place. A prefix that does not exist yet in the repository -- the
    ordinary case for a first draft -- walks components that are not symlinks and
    is not refused.
    """
    redirected = workspace.redirected_destinations(ws, allowed)
    if redirected:
        raise LoopRefusal(
            f"in the repository {ws.repo_root}, a symlink stands on the path to "
            f"{', '.join(redirected)}. apply_back refuses to copy through a symlinked "
            f"destination component, because writing through one lands outside the "
            f"allowlist while reporting a clean allowlisted write. Nothing about that "
            f"changes between rounds, so the whole round budget would be spent on a draft "
            f"that could never be applied. Resolve the link, or draft against a checkout "
            f"that does not carry it"
        )


def _fatal_condition(
    ws: workspace.Workspace, changed: Sequence[str], allowed: Sequence[str]
) -> str | None:
    """The name of a run-ending condition in this round's changes, or None.

    All three end the RUN. Nothing commits in the worktree, so a stray write, a
    deletion or a symlink stays in ``git status`` for every later round and makes
    every later ``apply_back`` raise the same refusal. Retrying spends rounds on a
    draft that can no longer come home -- at three rounds and a five-dollar
    ceiling each, up to fifteen dollars of unattended Opus on a draft already
    known to be unapplicable.

    The three conditions are tested in ``apply_back``'s own order and named after
    its own refusals, so the loop's attribution and the eventual refusal agree
    rather than each describing the round differently.

    Deletion is detected by absence on disk rather than by a status letter,
    because ``changed_paths`` reports paths and not codes. ``is_symlink`` is
    tested FIRST because ``exists`` follows links: without it a BROKEN symlink the
    draft wrote reports as a deletion, which ends the run correctly and attributes
    it to the wrong thing.
    """
    if workspace.stray_writes(changed, allowed):
        return "wrote-outside-allowlist"
    if any(_missing(ws.path / path) for path in changed):
        return "deleted-in-workspace"
    if workspace.unsupported_entries(ws, changed):
        return "unsupported-entry"
    return None


def _missing(path: Path) -> bool:
    """Gone from the worktree -- as opposed to present but not a regular file."""
    return not path.is_symlink() and not path.exists()


def _run_tests(
    ws: workspace.Workspace,
    expectation_module: Path,
    test_paths: Sequence[Path],
    timeout_s: int,
) -> verify.TestOutcome:
    """Inject the golden module, run the generated tests, and remove it again.

    The injection window is the barrier's weak point, so the removal is in a
    ``finally``: an exception between the copy and the unlink would otherwise
    leave the values sitting in the tree for every remaining round.
    """
    injected = ws.path / EXPECTATION_MODULE_NAME
    if injected.exists():
        raise BarrierViolation(
            f"{injected} already exists before injection. run_loop owns that path; a file "
            f"there is either a previous run that did not clean up or the draft writing to "
            f"it, and copying over it would hide which"
        )
    try:
        shutil.copy2(expectation_module, injected)
        return verify.run_pytest(
            [*test_paths, Path(EXPECTATION_MODULE_NAME)], ws.path, timeout_s=float(timeout_s)
        )
    finally:
        injected.unlink(missing_ok=True)


def _persist(
    round_dir: Path,
    outcome: verify.TestOutcome | None,
    client_text: str,
    changed: Sequence[str],
    failures: Sequence[str],
    signature: str,
    elapsed: float,
    brief: Mapping[str, Any],
    ws: workspace.Workspace,
) -> None:
    """Write this round's record beside its prompt.

    ``pytest.txt`` holds raw output, which quotes the expected values. It is
    written under ``artifacts_dir``, which :func:`_checked_paths` has already
    refused if it sits inside the worktree.
    """
    if outcome is None:
        (round_dir / "pytest.txt").write_text(
            "(the tests were not run this round)\n", encoding="utf-8"
        )
    else:
        (round_dir / "pytest.txt").write_text(outcome.raw, encoding="utf-8")

    todos = parser_todos(ws.path, str(brief.get("adapter_name") or ""))
    record: dict[str, Any] = {
        "signature": signature,
        "passed": bool(outcome and outcome.passed),
        "verdict": outcome.verdict if outcome else "not-run",
        "returncode": outcome.returncode if outcome else None,
        "elapsed_s": round(elapsed, 3),
        "changed_paths": list(changed),
        "failures_redacted": list(failures),
        "todos": [{"field": t.field, "line": t.line, "text": t.text} for t in todos],
        "client_text": client_text,
    }
    (round_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def _expectations_from(brief: Mapping[str, Any]) -> list[ExpectedRecord]:
    """Golden records carried on the brief, when a caller did not pass them.

    ``brief.json`` does not normally carry them -- the reader writes them to
    their own file and Task 15 hands them in -- so the usual answer is the empty
    list. That is safe: :func:`redact` rebuilds from the node id and does not
    depend on knowing the values.
    """
    raw = brief.get("expectations") or []
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        return []
    records: list[ExpectedRecord] = []
    for entry in raw:
        if isinstance(entry, ExpectedRecord):
            records.append(entry)
        elif isinstance(entry, Mapping) and isinstance(entry.get("values"), Mapping):
            records.append(
                ExpectedRecord(
                    record_key=str(entry.get("record_key") or ""),
                    values={str(k): str(v) for k, v in entry["values"].items()},
                )
            )
    return records
