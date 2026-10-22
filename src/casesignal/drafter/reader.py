"""The reader pass: what the fixtures say, before any code exists to read.

This is the first of the drafter's two agent seams, and the one the verification
model rests on. Field identification cannot be made deterministic: nothing in a DOM
says that a ``<strong>AGE:</strong>`` run means the victim's age, and nothing in a
Socrata column named ``DEC_AGE`` says it either. Somebody has to supply the
semantics, so an agent does.

*Why it is split from the parser pass.* If one agent wrote both the parser and the
values the parser is tested against, a green suite would only prove the parser
agrees with itself. So the reader runs at capture time, sees nothing but the
captured fixtures, and writes two data files: ``locators.json`` (how to find each
field) and ``expectations.json`` (golden values, transcribed by hand, for three
named records). The parser pass in Task 13 writes the code and must never see the
second file — an information barrier that task asserts as a tested property.

What the agent supplies is semantics and nothing else. Python then applies the
locators to the captured records itself (Task 10), measures coverage, and derives
the test floors from the measurement. The agent is never asked how well its own
locators work.

*Why this module is a file interface rather than a dispatch.* Same shape as
:mod:`casesignal.scout.classify`: a schema constant, a prompt builder, and strict
loaders around the gap where an agent runs. :func:`run_reader` closes the gap
through :class:`casesignal.drafter.client.DrafterClient`, but every part of the
contract is usable — and testable — without spawning anything.

*Why the loaders refuse rather than degrade.* Everything downstream is built on
this output: coverage numbers become test floors, and golden values become the
only assertions that a parser reads the source correctly rather than consistently.
A locator quietly dropped for being malformed is a field with no floor and no test,
which reads as success. So an unknown ``kind``, a missing ``values``, a null where a
string belongs, or a record whose expectations are empty all raise
:class:`InvalidReaderOutput`, and the message quotes the offending value.

The same rule applies one level up, to the file. An empty ``locators.json`` or an
empty ``expectations.json`` parses cleanly and asserts nothing: the inventory pass
iterates no locators so it cannot report a miss, no coverage floor is derived, no
golden test is rendered, and verify resolves the draft to PASS with nothing actually
verified. Both are refused here, which is the only place in the chain where that is
still visible.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casesignal.drafter.client import DEFAULT_MODEL, DrafterClient
from casesignal.scout.models import Candidate, FieldSpec, LocatorKind, Page

LOCATORS_FILENAME = "locators.json"
EXPECTATIONS_FILENAME = "expectations.json"

# The field-inventory vocabulary from SP1 (see scout/classify.py). Used only when a
# candidate arrives without a filled inventory: the locator keys have to match the
# inventory keys or Task 10's apply_to_inventory writes coverage onto nothing, so a
# candidate that HAS an inventory drives the field list from it instead of from here.
CANONICAL_FIELDS: tuple[str, ...] = (
    "victim_name",
    "race",
    "sex",
    "age",
    "county",
    "city",
    "address",
    "incident_date",
    "case_number",
    "narrative",
    "photo",
    "contact",
)

# The reader's tool grant, a strict subset of the client's ALLOWED_TOOLS.
#
# Edit is absent. The reader creates two files that do not exist yet and has no
# reason to change one that does — and the round runs inside a worktree holding the
# whole repository, so Edit is the difference between an agent that writes two JSON
# files and an agent that can rewrite any source file in the tree. Glob is absent
# because the prompt names every fixture path explicitly; the reader has nothing to
# discover. Grep stays: a listing fixture can be a megabyte of markup, and locating
# a label by search rather than by reading the whole document is the difference
# between one round and a context overflow.
#
# Bash was never available (client.ALLOWED_TOOLS omits it), so the reader cannot run
# the capture, the tests, or anything else. It reads, it searches, it writes.
READER_TOOLS: tuple[str, ...] = ("Read", "Grep", "Write")

# A round bound in dollars as well as in seconds. Task 8 left ``max_budget_usd``
# defaulting to None so a caller opts in deliberately; an opt-in nobody exercises is
# no ceiling at all, so this pass names one. Sized for a handful of large fixtures
# read once, not for an agent that decides to re-read the corpus.
DEFAULT_READER_BUDGET_USD = 3.0
DEFAULT_READER_TIMEOUT_S = 600

_KIND_VALUES: tuple[str, ...] = tuple(sorted(kind.value for kind in LocatorKind))
_PAGE_VALUES: tuple[str, ...] = tuple(page.value for page in Page)

LOCATORS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "field name -> how to find that field inside one captured record",
    "additionalProperties": {
        "type": "object",
        "required": ["kind", "value", "page"],
        "properties": {
            "kind": {"enum": list(_KIND_VALUES)},
            "value": {"type": "string"},
            "page": {"enum": list(_PAGE_VALUES)},
        },
    },
}

EXPECTATIONS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "description": "golden values transcribed from the fixtures, one entry per sampled record",
    "items": {
        "type": "object",
        "required": ["record_key", "values"],
        "properties": {
            "record_key": {"type": "string"},
            "values": {"type": "object", "additionalProperties": {"type": "string"}},
        },
    },
}


class InvalidReaderOutput(ValueError):
    """Raised when the reader pass did not produce output this module will accept.

    Covers the round producing nothing at all as well as producing something
    malformed: from every consumer's point of view those are the same event, and
    both mean no locator and no golden value may be trusted from this run.
    """


@dataclass(frozen=True)
class Locator:
    """How to find one canonical field inside one captured record.

    ``value`` is interpreted by ``kind``: a CSS selector, a literal on-page label
    whose line remainder is the value, or a dotted path of JSON object keys.
    ``page`` is ``"list"`` or ``"detail"`` — which captured surface carries it,
    matching :attr:`casesignal.drafter.shapes.base.CapturedRecord.page`.
    """

    field: str
    kind: LocatorKind
    value: str
    page: str


@dataclass(frozen=True)
class ExpectedRecord:
    """Golden values for one sampled record, read off the fixture by the agent.

    ``record_key`` is a capture's own record key — ``"<fixture>#<index>"`` — so the
    generated expectation test can find the record it is talking about. ``values``
    maps field name to the value exactly as the source prints it.
    """

    record_key: str
    values: dict[str, str]


def build_reader_prompt(
    candidate: Candidate,
    fixture_paths: Sequence[str],
    out_dir: Path,
) -> str:
    """The reader round's whole instruction: read these fixtures, write these two files.

    The field list comes from the candidate's own SP1 field inventory when it has
    one, restricted to the fields the classifier marked present. That is not a
    convenience: Task 10 joins locators onto the inventory by field name, and a
    locator keyed ``victim_age`` against an inventory keyed ``age`` measures nothing.
    Absent fields are excluded because a locator that matches no record at all is a
    hard error in the inventory pass, by design.
    """
    if not fixture_paths:
        # The whole round is "read these fixtures and transcribe what they say". With
        # none named, the prompt asks for golden values from nowhere, and the round is
        # bought and billed before it can fail. A capture that produced no listing
        # fixtures is an operator's problem, not an agent's.
        raise InvalidReaderOutput(
            f"refusing to build a reader prompt for {candidate.id} with no fixtures: "
            f"there would be nothing to read and nothing to transcribe"
        )
    paths = "\n".join(f"  - {path}" for path in fixture_paths)
    fields = _field_lines(candidate)
    locators_path = (out_dir / LOCATORS_FILENAME).as_posix()
    expectations_path = (out_dir / EXPECTATIONS_FILENAME).as_posix()
    return f"""You are reading captured fixtures from a cold-case data source so that a
LATER pass can write a parser for it. You are not writing code, and no parser exists
yet for you to read. Your entire output is two JSON files.

Candidate: {candidate.id}
Index URL: {candidate.index_url}
Channel: {candidate.channel.value}

Read ONLY these captured fixtures. Do not browse, and do not read anything else in
the tree:
{paths}

=== 1. {locators_path} ===

For each field below, say HOW to find its value inside one record's markup or JSON.
Key each entry by the field name exactly as written here:
{fields}

Each entry is an object with kind, value and page:
  kind "css"        value is a CSS selector matched against the record's markup.
  kind "label"      value is the literal on-page label that introduces the field
                    (for example "COUNTY:"); the value is the rest of that line.
  kind "json_path"  value is a dotted path of object keys, e.g. attributes.CASE_NO.
  page is "list" or "detail": which captured surface the field appears on.

Omit a field entirely rather than guessing. A locator that matches nothing in every
record is a hard error in the next pass; a locator that matches the WRONG thing is
worse, because it becomes a passing test.

Never infer race; only record whether the SOURCE provides it as a field. A race
locator is emitted only when the source publishes race as a field of its own. Race is
never derived from a name, a photograph, a narrative, or anything else, here or
anywhere downstream.

Schema for this file:
{json.dumps(LOCATORS_SCHEMA, indent=2)}

=== 2. {expectations_path} ===

Golden values for exactly three records, transcribed from the fixtures by hand:
  1. the FIRST record of the first listing fixture;
  2. the LAST record of the last listing fixture;
  3. the most DEGENERATE record in the capture, meaning the one carrying the fewest
     of the fields above. Break ties by taking the earliest.

record_key is "<listing fixture file name>#<zero-based position of the record within
that fixture>", for example "listing_1.html#0". The key always names the LISTING
fixture and the record's position in it, even when you read the values off that
record's own detail page.

values maps field name to the value EXACTLY as the source prints it: no
normalisation, no reformatting of dates, no re-casing, no trimming of interior
punctuation. Every value is a JSON string, so quote numbers. Include only the fields
that record actually carries, and never a field you had to infer.

Schema for this file:
{json.dumps(EXPECTATIONS_SCHEMA, indent=2)}

Write both files and emit no other output. Do not create, modify or delete anything
else."""


def requested_fields(candidate: Candidate) -> dict[str, FieldSpec]:
    """Exactly the fields the prompt will ask a reader to locate.

    Empty means the prompt falls back to :data:`CANONICAL_FIELDS`, which is a
    different question from "no fields": it is what a candidate with no inventory, or
    one whose inventory marks everything absent, is asked. The prompt builder and
    run_reader's stray-locator check both read this, so what was asked for and what is
    accepted back cannot drift apart.
    """
    return {name: spec for name, spec in candidate.fields.items() if spec.present}


def asked_fields(candidate: Candidate) -> tuple[str, ...]:
    """The field names this prompt actually lists, fallback included.

    :func:`requested_fields` answers "which inventory fields are present", and returns
    empty for a candidate that has no inventory -- which, as its own docstring says, is a
    different question from "no fields": that candidate is asked for
    :data:`CANONICAL_FIELDS`. This answers the question a consumer usually wants, which is
    what the round was asked for, and it is the denominator Task 10 measures omissions
    against. Kept here, beside the prompt it describes, so the fallback is expressed once.
    """
    present = requested_fields(candidate)
    return tuple(present) if present else CANONICAL_FIELDS


def _field_lines(candidate: Candidate) -> str:
    """One bullet per field to locate, annotated with what SP1 already knows."""
    present = requested_fields(candidate)
    lines = []
    for name in asked_fields(candidate):
        spec = present.get(name)
        if spec is None:  # the canonical fallback: nothing recorded to annotate with
            lines.append(f"  - {name}")
            continue
        page = spec.page.value if spec.page is not None else "unknown page"
        lines.append(f"  - {name} (recorded as {spec.location.value}, on the {page})")
    return "\n".join(lines)


def load_locators(path: Path) -> dict[str, Locator]:
    """Parse ``locators.json``, refusing anything downstream could misread."""
    data = _load_json(path, LOCATORS_FILENAME)
    if not isinstance(data, dict):
        raise InvalidReaderOutput(
            f"{path}: {LOCATORS_FILENAME} must be a JSON object mapping field name to "
            f"locator, got {type(data).__name__}"
        )
    if not data:
        # The same principle this module already applies one level down, at the record.
        # An empty file parses cleanly, so measure() iterates nothing, LocatorMatchedNothing
        # cannot fire, floors() returns {}, no coverage test is rendered, and verify
        # resolves PASS on an adapter nobody checked. Refusing an empty locators file is
        # the only place that chain can be broken.
        raise InvalidReaderOutput(
            f"{path}: {LOCATORS_FILENAME} names no fields at all; a draft with no "
            f"locators measures nothing, and every derived floor would be vacuous"
        )
    locators: dict[str, Locator] = {}
    for field_name, spec in data.items():
        if not field_name.strip():
            raise InvalidReaderOutput(f"{path}: locator field name must not be blank")
        if not isinstance(spec, dict):
            raise InvalidReaderOutput(
                f"{path}: locator for {field_name!r} must be an object with kind/value/"
                f"page, got {spec!r}"
            )
        kind = _text(spec.get("kind"), f"{path}: locator {field_name!r} 'kind'")
        if kind not in _KIND_VALUES:
            raise InvalidReaderOutput(
                f"{path}: locator {field_name!r} has unknown kind {kind!r}; "
                f"expected one of {', '.join(_KIND_VALUES)}"
            )
        page = _text(spec.get("page"), f"{path}: locator {field_name!r} 'page'")
        if page not in _PAGE_VALUES:
            raise InvalidReaderOutput(
                f"{path}: locator {field_name!r} has unknown page {page!r}; "
                f"expected one of {', '.join(_PAGE_VALUES)}"
            )
        locators[field_name] = Locator(
            field=field_name,
            kind=LocatorKind(kind),
            value=_text(spec.get("value"), f"{path}: locator {field_name!r} 'value'"),
            page=page,
        )
    return locators


def load_expectations(path: Path) -> list[ExpectedRecord]:
    """Parse ``expectations.json``, refusing anything that would assert nothing.

    An entry with no values is rejected along with the malformed ones. It parses
    cleanly and renders a test that passes unconditionally, which is the exact
    failure this whole two-pass arrangement exists to prevent.
    """
    data = _load_json(path, EXPECTATIONS_FILENAME)
    if not isinstance(data, list):
        raise InvalidReaderOutput(
            f"{path}: {EXPECTATIONS_FILENAME} must be a JSON array of records, got "
            f"{type(data).__name__}"
        )
    if not data:
        raise InvalidReaderOutput(
            f"{path}: {EXPECTATIONS_FILENAME} holds no records at all; with no golden "
            f"values nothing distinguishes a parser that reads the source from one that "
            f"agrees with itself, which is what the two passes exist to separate"
        )
    records: list[ExpectedRecord] = []
    seen: set[str] = set()
    for position, entry in enumerate(data):
        where = f"{path}: expectation {position}"
        if not isinstance(entry, dict):
            raise InvalidReaderOutput(
                f"{where} must be an object with 'record_key' and 'values', got {entry!r}"
            )
        record_key = _text(entry.get("record_key"), f"{where} 'record_key'")
        if record_key in seen:
            raise InvalidReaderOutput(
                f"{where} repeats record_key {record_key!r}; each sampled record is expected once"
            )
        seen.add(record_key)
        values = entry.get("values")
        if not isinstance(values, dict):
            raise InvalidReaderOutput(
                f"{where} ({record_key!r}) must carry 'values' as an object of field "
                f"name to expected value, got {values!r}"
            )
        if not values:
            raise InvalidReaderOutput(
                f"{where} ({record_key!r}) carries no 'values'; an expectation that "
                f"asserts nothing would render a test that always passes"
            )
        for name, value in values.items():
            if not name.strip():
                raise InvalidReaderOutput(
                    f"{where} ({record_key!r}) has a blank field name in 'values'"
                )
            if not isinstance(value, str):
                raise InvalidReaderOutput(
                    f"{where} ({record_key!r}) expects {name!r} to be {value!r}, which is "
                    f"a {type(value).__name__}; every expected value must be the source's "
                    f"own text, quoted as a JSON string"
                )
            if not value.strip():
                # The likeliest wrong move on the degenerate record this prompt asks
                # for: emitting "" for the fields it lacks instead of omitting them.
                # `assert extracted == ""` is passed by a parser that never found the
                # field, so it is a golden test asserting the opposite of its purpose.
                raise InvalidReaderOutput(
                    f"{where} ({record_key!r}) expects {name!r} to be blank; omit the "
                    f"field instead, because an empty expectation is satisfied by a "
                    f"parser that fails to extract it at all"
                )
        records.append(ExpectedRecord(record_key=record_key, values=dict(values)))
    return records


def _run_reader(
    candidate: Candidate,
    client: DrafterClient,
    *,
    fixture_paths: Sequence[str],
    out_dir: Path,
    cwd: Path,
    model: str = DEFAULT_MODEL,
    timeout_s: int = DEFAULT_READER_TIMEOUT_S,
    max_budget_usd: float | None = DEFAULT_READER_BUDGET_USD,
) -> tuple[dict[str, Locator], list[ExpectedRecord]]:
    """Run one reader round and return what it wrote, or refuse.

    ``out_dir`` must sit inside ``cwd``, and that is checked rather than documented:
    ``--restricted`` confines the file tools to the working directory, so an out_dir
    outside it names a path the agent cannot write. Unchecked, the round is bought and
    then reported as "the reader left no locators.json", which sends the operator after
    the agent instead of after the call.
    """
    workdir = cwd.resolve()
    target = out_dir.resolve()
    if target != workdir and workdir not in target.parents:
        raise InvalidReaderOutput(
            f"out_dir {out_dir} is outside the reader's working directory {cwd}; "
            f"--restricted confines the file tools to the working directory, so the "
            f"round could not write there"
        )
    prompt = build_reader_prompt(candidate, fixture_paths, out_dir)
    result = client.run(
        prompt,
        allowed_tools=READER_TOOLS,
        model=model,
        cwd=cwd,
        timeout_s=timeout_s,
        max_budget_usd=max_budget_usd,
    )
    if not result.ok:
        raise InvalidReaderOutput(f"the reader round failed: {result.text}")
    locators = load_locators(out_dir / LOCATORS_FILENAME)
    # Binding the prompt's field list to the inventory makes the Task 10 join correct
    # by INSTRUCTION; this makes it correct by construction. The failure it closes is
    # silent in every other layer: a locator keyed `victim_age` against an inventory
    # keyed `age` matches the markup perfectly, so measure() reports healthy coverage
    # and never raises LocatorMatchedNothing, and apply_to_inventory then finds no
    # FieldSpec to write it onto. The field simply has no floor, and its absence is
    # the only signal. Only checkable where both halves are in hand, which is here and
    # not in load_locators.
    #
    # Measured against what the prompt ASKED FOR — present fields — rather than against
    # every key in the inventory. An absent field has a FieldSpec, so the join would not
    # break, and Task 10 would eventually raise LocatorMatchedNothing on a locator that
    # matches nothing. But one that matches SOMETHING is the case that matters: a
    # locator on an absent `race` field, pointed at any real element, manufactures
    # coverage for a field the source does not publish, and race is the field where this
    # platform's standing rule makes that least acceptable. This is the last point where
    # it can be refused before the round's output is trusted.
    requested = requested_fields(candidate)
    if requested:
        stray = sorted(set(locators) - set(requested))
        if stray:
            raise InvalidReaderOutput(
                f"the reader emitted locators for fields the prompt did not ask for: "
                f"{', '.join(stray)}. It asked for {', '.join(sorted(requested))} — the "
                f"fields the candidate's inventory marks present. A locator under any "
                f"other name measures fine and then joins onto nothing, and a locator on "
                f"a field the source does not publish manufactures coverage for it"
            )
    return (locators, load_expectations(out_dir / EXPECTATIONS_FILENAME))


def _load_json(path: Path, described: str) -> Any:
    """Read and parse one reader output file, naming it in every refusal."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidReaderOutput(
            f"the reader pass did not leave a readable {described} at {path} ({exc})"
        ) from exc
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except _DuplicateKey as exc:
        raise InvalidReaderOutput(
            f"{path}: {described} repeats the object key {exc.key!r}. JSON resolves a "
            f"repeated key last-wins, so one of the two would vanish with no error — the "
            f"same two-things-one-identity problem refused at the record level"
        ) from exc
    except ValueError as exc:
        raise InvalidReaderOutput(f"{path}: {described} is not valid JSON ({exc})") from exc


class _DuplicateKey(Exception):
    """A repeated key inside one JSON object. Not a ValueError: it must not be caught
    by the malformed-JSON handler, because the document parses perfectly well."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` that refuses a repeated key instead of silently dropping one."""
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise _DuplicateKey(key)
        seen.add(key)
    return dict(pairs)


def _text(value: Any, described: str) -> str:
    """A non-blank string, or a refusal quoting what was there instead."""
    if not isinstance(value, str):
        raise InvalidReaderOutput(f"{described} must be a string, got {value!r}")
    if not value.strip():
        raise InvalidReaderOutput(f"{described} must not be blank, got {value!r}")
    return value


def run_reader(
    candidate: Candidate,
    client: DrafterClient,
    *,
    fixture_paths: Sequence[str],
    out_dir: Path,
    cwd: Path,
    model: str = DEFAULT_MODEL,
    timeout_s: int = DEFAULT_READER_TIMEOUT_S,
    max_budget_usd: float | None = DEFAULT_READER_BUDGET_USD,
) -> tuple[dict[str, Locator], list[ExpectedRecord]]:
    """Expose copies of evidence, never the authoritative capture directory.

    The reader CLI confines file tools to this disposable directory. Compare
    copied AND original bytes before accepting output; output paths and the
    authoritative manifest are never writable through the reader's file tools.
    """
    root = cwd.resolve()
    target = out_dir.resolve()
    if target != root and root not in target.parents:
        raise InvalidReaderOutput(f"out_dir {out_dir} is outside the reader's working directory")
    if not fixture_paths:
        raise InvalidReaderOutput("no fixtures supplied to reader")
    evidence: dict[str, bytes] = {}
    for name in fixture_paths:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise InvalidReaderOutput(f"unsafe reader fixture path: {name}")
        source = (root / name).resolve()
        if root not in source.parents or not source.is_file():
            raise InvalidReaderOutput(f"missing or unsafe reader fixture: {name}")
        evidence[name] = source.read_bytes()
    with tempfile.TemporaryDirectory(prefix="casesignal-reader-") as directory:
        isolated = Path(directory)
        for name, raw in evidence.items():
            dest = isolated / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        result = _run_reader(
            candidate,
            client,
            fixture_paths=fixture_paths,
            out_dir=isolated,
            cwd=isolated,
            model=model,
            timeout_s=timeout_s,
            max_budget_usd=max_budget_usd,
        )
        for name, raw in evidence.items():
            copy = isolated / name
            source = root / name
            if (
                copy.is_symlink()
                or not copy.is_file()
                or copy.read_bytes() != raw
                or source.read_bytes() != raw
            ):
                raise InvalidReaderOutput(f"reader changed captured evidence: {name}")
        target.mkdir(parents=True, exist_ok=True)
        for name in (LOCATORS_FILENAME, EXPECTATIONS_FILENAME):
            output = isolated / name
            if output.is_symlink():
                raise InvalidReaderOutput(f"reader output must be a regular file: {name}")
            (target / name).write_bytes(output.read_bytes())
        return result
