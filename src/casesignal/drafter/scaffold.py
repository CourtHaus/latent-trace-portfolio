"""The generator: a measured brief in, a draft adapter and its tests out.

This is the pass that turns everything the earlier passes established into files
a human edits. It writes an adapter package modelled on ``cold_case_ok_osbi``,
appends the source-catalog entry, registers the adapter in the hand-maintained
registry, renders two generated test modules, and writes the source-facts memo.

*What it refuses.* An unmeasured brief, and that is not one check but three. The
capture pass writes ``brief.json`` with ``inventory_measured: false``; the
inventory pass rewrites it. Nothing between them guarantees the rewrite ever
happened, so an unmeasured brief will arrive here, and generating from one
produces a full adapter package whose every floor is fiction and whose test
module is green. The flag alone is not enough either: a brief can carry
``inventory_measured: true`` over an empty ``floors`` block, and an empty block
and a block whose every floor is 0.0 are the same artefact to this module -- an
invariant module with no coverage test that can go red. So :class:`Brief` refuses
at construction, which makes the unmeasurable state unrepresentable rather than
merely unwritten.

*What it drops silently and says so loudly.* A MIXTURE -- one real floor and
three vacuous ones -- passes the inventory pass's own refusal, because at least
one floor can fail. A ``test_coverage_floor_x`` rendered for a floor of 0.0
always passes, so none is rendered; the field is named in a comment in the
generated module and in the memo's advisory section instead.

*Vocabulary.* Locators and golden values both arrive from the reader in SP1
inventory names (``age``, ``victim_name``). The mapping to adapter names is
:data:`casesignal.drafter.inventory.ADAPTER_FIELD_NAMES` and it is imported, not
re-derived: a second copy of that table is a second thing to drift.
:func:`render_expectation_tests` remaps its own input, so a caller that hands it
raw reader output gets the same result as one that hands it remapped output --
the mapping is idempotent, every adapter name being either absent from the table
or mapped to itself.

*Identity.* Both shared-file edits key on ``adapter_name``. ``source_key``
carries the capture date and changes every run; keying on it would append a
second catalog entry per re-draft and leave the pipeline with two definitions
for one adapter.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from casesignal.drafter import capture as _capture
from casesignal.drafter import templates
from casesignal.drafter.inventory import remap_expectations
from casesignal.drafter.reader import ExpectedRecord
from casesignal.drafter.templates import render

__all__ = [
    "Brief",
    "UnmeasuredBrief",
    "ScaffoldRefusal",
    "append_source_yaml",
    "class_name_for",
    "is_generated_by_us",
    "is_marker_line",
    "register_adapter",
    "render_expectation_tests",
    "render_invariant_tests",
    "render_memo",
    "scaffold",
    "source_yaml_entry",
    "stamp_generated",
]

# The reader pass is told to transcribe the first record, the last record, and the
# most degenerate one it can find. The loader cannot enforce "three": a run that
# transcribed one easy record produces a well-formed expectations.json that passes
# every upstream check. So the count travels into the generated module and is
# asserted there, the same way an unreachable floor travels into a test that is red
# from the first run rather than into a log line nobody reads.
MINIMUM_EXPECTATION_SET = 3

# Line length the repo's formatter enforces; used only to decide whether a generated
# import fits on one line, matching the mixed style already in run_pipeline.py.
_LINE_LENGTH = 100

# A field name becomes a SQL column, a Python identifier and a test-function suffix in
# generated source. Reader agents choose these names, so they are checked rather than
# trusted: an unchecked name is an injection into a CREATE TABLE this module writes.
_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")

# The marker line this generator stamps as the final line of every file it writes,
# and the only thing that distinguishes its own output from anybody else's. The
# digest covers everything above the line, over LF-normalised text so a CRLF
# checkout (this repository is core.autocrlf=true) verifies the same as an LF one.
_MARKER_LINE = re.compile(
    r"(?:#|<!--)[ \t]*drafted-by: (?P<marker>.+?); session=(?P<session>[^;]*); "
    r"at=(?P<at>[^;]*); sha256=(?P<digest>[0-9a-f]{64})[ \t]*(?:-->)?[ \t]*\Z"
)

# Postgres truncates an identifier at 63 bytes, so two column names that agree for
# 63 bytes are one column and the generated CREATE TABLE is rejected -- or worse,
# accepted with one of them silently gone. The guard's job is to check, not to
# assume the reader chose short names.
_IDENTIFIER_MAX = 63

# The raw table this generator writes is `raw_cold_case.{adapter_name}_dv{N}`, and
# `{adapter_name}_dv{N}` is ONE Postgres identifier. capture's 64-character limit is
# about a path component, and a name at that limit yields a 69-byte table identifier
# -- the same truncation defect the field-name bound was added for, one level up from
# the columns it fixed. Nine digits of dataset_version_id is 999,999,999 versions.
_DATASET_VERSION_DIGITS = 9
ADAPTER_NAME_MAX = min(
    _capture._ADAPTER_NAME_MAX, _IDENTIFIER_MAX - len("_dv") - _DATASET_VERSION_DIGITS
)

# A US state or territory postal code, and nothing else. `state` is the one value
# in a brief that decides a FILESYSTEM PATH -- the catalog file is
# `cold_case_<state>.yaml` -- and it originates in an LLM classifier verdict whose
# schema (scout/classify.py) is `{"type": ["string", "null"]}`: no pattern, no
# enum. `state="x/../../../.."` is a valid verdict, a valid Candidate and, until
# this existed, a valid write outside repo_root. The blank check that used to
# stand here checked that the classifier said SOMETHING, which is a different
# question from whether what it said can name a file.
_STATE_CODE = re.compile(r"[A-Za-z]{2}\Z")

_ADAPTER_IMPORT_PREFIX = "from casesignal.etl.adapters."
_REGISTER_CALL = "registry.register("
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


class ScaffoldRefusal(ValueError):
    """Raised when the scaffold pass will not generate from what it was handed."""


class UnmeasuredBrief(ScaffoldRefusal):
    """Raised when a brief's floors would grade a drafted adapter against nothing.

    Three routes reach here and the message names which one: the inventory pass
    never ran, it ran and produced no floors, or it produced floors none of which
    can fail. All three render the same artefact -- a generated invariant module
    with no coverage test that can go red -- and all three read downstream as a
    draft that passed.
    """


@dataclass(frozen=True)
class Brief:
    """A measured capture, in the shape the generator consumes.

    The first seven fields are the contract every consumer binds to. Everything
    after them is appended with a default, so a construction that names only the
    seven still binds, and so a brief written by an older capture still loads.

    ``floors``, ``locators`` and ``coverage`` are keyed in **adapter** vocabulary,
    because :func:`casesignal.drafter.inventory.write_measured_brief` remapped them
    before writing. ``expectations`` are the exception: they come off the reader's
    own file and are still in inventory vocabulary, so
    :func:`render_expectation_tests` remaps them.
    """

    adapter_name: str
    source_key: str
    state: str
    floors: Mapping[str, float]
    records_captured: int
    records_total: int | None
    listing_record_count: int

    runtime: Mapping[str, Any] = field(default_factory=dict)
    fixture_manifest: tuple[Mapping[str, Any], ...] = ()
    inventory_measured: bool = False
    truncated: bool = False
    record_list_identified: bool = True
    measured_over_unidentified_records: bool = False

    agency: str | None = None
    agency_type: str | None = None
    county: str | None = None
    level: str | None = None
    index_url: str = ""
    channel: str = ""
    page_type: str | None = None
    shape: str = ""
    transport: str = ""
    robots: str | None = None

    session_id: str = ""
    captured_at: str = ""
    fixtures_root: str = ""
    listing_paths: tuple[str, ...] = ()
    detail_paths: tuple[str, ...] = ()
    listing_pages: int = 0
    pagination_kind: str = "single"
    pagination_detail: str | None = None
    detail_url_pattern: str | None = None
    dataset_id: str | None = None
    source_id_strategy: str | None = None
    source_id_field: str | None = None
    case_type_mix: tuple[str, ...] = ()

    locators: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    coverage: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    expectations: tuple[ExpectedRecord, ...] = ()

    requested_fields: tuple[str, ...] = ()
    omitted_fields: tuple[str, ...] = ()
    omission_rate: float = 0.0
    unreachable_floors: tuple[str, ...] = ()
    vacuous_floors: tuple[str, ...] = ()
    suspected_page_mismatch: tuple[str, ...] = ()
    accepted_findings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _checked_adapter_name(self.adapter_name)
        if not _STATE_CODE.match(self.state):
            raise ScaffoldRefusal(
                f"state {self.state!r} is not a two-letter postal code. It names the "
                f"source-catalog file this generator writes "
                f"(src/casesignal/etl/sources/cold_case_<state>.yaml), so anything else "
                f"is a path this pass had no business choosing -- and it arrives from a "
                f"classifier verdict typed only as 'string or null'"
            )
        if not self.inventory_measured:
            raise UnmeasuredBrief(
                f"refusing to generate from {self.adapter_name}: the brief says "
                f"inventory_measured is false, so no locator has been applied to a "
                f"captured record and every floor a generated test would assert is a "
                f"number nobody measured. Run the inventory pass "
                f"(inventory.write_measured_brief) before drafting"
            )
        if not self.floors:
            raise UnmeasuredBrief(
                f"refusing to generate from {self.adapter_name}: the brief says "
                f"inventory_measured is true over an empty floors block. The generated "
                f"invariant module would carry no coverage test at all and would resolve "
                f"green over an adapter nobody has checked"
            )
        if not any(floor > 0.0 for floor in self.floors.values()):
            raise UnmeasuredBrief(
                f"refusing to generate from {self.adapter_name}: every derived floor is "
                f"0.0 ({', '.join(sorted(self.floors))}). A floor of zero is satisfied by "
                f"a parser that extracts the field never, so no generated coverage test "
                f"could go red"
            )
        for name in sorted(self.floors):
            _checked_field(name, "floor")

    @property
    def failing_floors(self) -> dict[str, float]:
        """The floors a generated test is rendered for: everything above 0.0.

        A vacuous floor survives :meth:`__post_init__` whenever at least one other
        floor can fail, and it is the mixture -- one real floor, three vacuous -- that
        the inventory pass's own refusal cannot see.
        """
        return {name: floor for name, floor in self.floors.items() if floor > 0.0}

    @property
    def is_census(self) -> bool:
        """Was the corpus walked exhaustively, so an exact record count is checkable?

        Three conditions, not one. A truncated walk always reports an unknown total,
        but a total can be unknown without truncation, and a total that equals the
        capture is only a census if the walk also finished.
        """
        return (
            self.records_total is not None
            and self.records_total == self.records_captured
            and not self.truncated
        )

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        expectations: Sequence[ExpectedRecord] = (),
    ) -> Brief:
        """Build a brief from a decoded ``brief.json``, keeping every refusal."""
        known = set(cls.__dataclass_fields__)
        tuple_fields = {
            "listing_paths",
            "detail_paths",
            "case_type_mix",
            "requested_fields",
            "omitted_fields",
            "unreachable_floors",
            "vacuous_floors",
            "suspected_page_mismatch",
            "accepted_findings",
        }
        kwargs: dict[str, Any] = {}
        for name, value in data.items():
            if name not in known or name == "expectations":
                continue
            kwargs[name] = tuple(value or ()) if name in tuple_fields else value
        kwargs["expectations"] = tuple(expectations)
        return cls(**kwargs)


# --- naming ---


def class_name_for(adapter_name: str) -> str:
    """``cold_case_ok_osbi`` -> ``ColdCaseOkOsbiAdapter``.

    One rule with no exceptions. The repository's existing class names are not
    self-consistent (``ColdCaseOKOSBIAdapter`` beside ``ColdCaseMnBcaAdapter``), so
    any rule disagrees with some of them; a rule that title-cases every part agrees
    with the most recent convention and, more importantly, is predictable from the
    adapter name alone, which is what the registry edit needs.
    """
    parts = [part for part in adapter_name.split("_") if part]
    if not parts:
        raise ScaffoldRefusal("adapter_name has no parts to build a class name from")
    return "".join(part[:1].upper() + part[1:] for part in parts) + "Adapter"


def source_code_for(adapter_name: str, state: str) -> str:
    """``cold_case_ok_osbi`` + ``OK`` -> ``OSBI_OK``, the catalog's short code.

    A draft value. The existing codes are inconsistent (``ASP_AR``, ``NH_DOJ``,
    ``BCA_MN``) and no consumer parses them, so this produces the commonest shape and
    leaves an operator free to edit it.
    """
    parts = [part for part in adapter_name.split("_") if part]
    for prefix in ("cold", "case"):
        if parts and parts[0] == prefix:
            parts.pop(0)
    lowered = state.strip().lower()
    agency_parts = [part for part in parts if part != lowered]
    stem = "_".join(agency_parts).upper() if agency_parts else "SOURCE"
    return f"{stem}_{state.strip().upper()}"


def _checked_adapter_name(name: str) -> str:
    """The adapter name, or a refusal.

    It is a package directory, a module path in two generated imports, a raw table
    name in generated SQL, a YAML key and a test-module filename. Nothing between the
    brief on disk and those uses re-checks it: ``capture.adapter_name_for`` validates
    the name it derives, but a brief.json is a file, and a hand-edited or
    hand-assembled one reaches here unchecked. The rule is capture's, read off
    capture's own constants rather than restated, so the two cannot drift.
    """
    if not _capture._ADAPTER_NAME_FORM.fullmatch(name):
        raise ScaffoldRefusal(
            f"adapter_name {name!r} is not a Python identifier in the house form "
            f"(lowercase, digits, underscores, leading letter). It names a package "
            f"directory, a generated import, and a raw table in generated SQL"
        )
    if len(name.encode("utf-8")) > ADAPTER_NAME_MAX:
        raise ScaffoldRefusal(
            f"adapter_name {name!r} is {len(name.encode('utf-8'))} bytes, over the "
            f"{ADAPTER_NAME_MAX}-byte limit. It is a path component in every file this "
            f"generator writes, and it is the stem of the raw table "
            f"raw_cold_case.{name}_dv<id>, which Postgres truncates at "
            f"{_IDENTIFIER_MAX} bytes"
        )
    return name


def _checked_field(name: str, described: str) -> str:
    """A measured field name, or a refusal.

    Field names come from a reader agent by way of the vocabulary table, and this
    module writes them into a ``CREATE TABLE``, a Python identifier and a test
    function name. Nothing downstream re-checks them.
    """
    if not _FIELD_NAME.match(name):
        raise ScaffoldRefusal(
            f"{described} {name!r} is not a lowercase identifier; it would be written "
            f"into generated SQL and generated Python as-is"
        )
    if len(name.encode("utf-8")) > _IDENTIFIER_MAX:
        raise ScaffoldRefusal(
            f"{described} {name!r} is {len(name.encode('utf-8'))} bytes, over Postgres' "
            f"{_IDENTIFIER_MAX}-byte identifier limit; the generated CREATE TABLE would "
            f"be written with it in full and truncated on the way in"
        )
    # No separate collision check for names that agree after truncation: with every
    # name at or under the limit, nothing is truncated, so two distinct names are two
    # distinct columns. The bound above is the whole of that guard, and a check for the
    # collision would be a branch no input could reach.
    return name


def _lit(value: object) -> str:
    """A Python literal for ``value``, double-quoted the way the formatter wants it.

    ``repr`` emits single quotes, which black rewrites on the drafted repository's
    first format run -- a diff on a generated file nobody edited. ``json.dumps``
    produces the double-quoted form directly and escapes what has to be escaped;
    ``ensure_ascii=False`` keeps a source's own accented names readable.
    """
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def _slug(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", value).strip("_").lower() or "record"


def _entries_key(adapter_name: str) -> str:
    return f"{adapter_name}_entries"


def _log_label(adapter_name: str, state: str) -> str:
    parts = [part for part in adapter_name.split("_") if part][2:]
    return " ".join(part.upper() for part in parts) or state.upper()


# --- shared-file edits, keyed on adapter_name ---


def _read_keeping_newlines(path: Path) -> tuple[str, str]:
    """The file's text with its own line endings, plus which ending it uses.

    ``Path.read_text`` translates CRLF to LF and ``write_text`` writes back LF, so a
    two-line insertion into a shared file rewrites every line of it. This repository
    is checked out with ``core.autocrlf=true``, so its working tree really is CRLF and
    that whole-file rewrite really would land in a drafted branch's diff: an
    unreviewable change to a hand-maintained file, produced by a generator nobody
    asked to reformat anything.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    return text, "\r\n" if "\r\n" in text else "\n"


def _write_keeping_newlines(path: Path, text: str, newline: str) -> None:
    """Write ``text`` verbatim, having already put ``newline`` where it belongs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


# The catalog files are hand-written YAML: block-folded descriptions, quoted release
# dates, blank lines between entries. A PyYAML round-trip preserves none of that --
# re-dumping the real cold_case_md.yaml to add one entry rewrote 83 of its 126 lines,
# reflowing six folded descriptions to plain scalars and stripping every separator.
# That is a pure reformat of a hand-maintained file, which is exactly what the
# newline-preservation work below exists to prevent; solving half of it was worse than
# useless, because the whole-file diff hides the two lines that matter.
#
# So the entry is RENDERED as text and SPLICED in by line, the way register_adapter
# already edits run_pipeline.py. Nothing outside the entry's own lines is read, parsed
# or rewritten.
_SOURCES_HEADER = re.compile(r"sources:[ \t]*(?P<empty>\[\])?[ \t]*\r?\n?\Z")
_ITEM_START = re.compile(r"(?P<indent>[ \t]*)-[ \t]")
_ADAPTER_LINE = re.compile(r"[ \t]*(?:-[ \t]+)?adapter_name:[ \t]*(.+?)[ \t]*\r?\n?\Z")

# Where the description folds. The existing files wrap around here.
_DESCRIPTION_WIDTH = 68


def _yaml_scalar(value: Any) -> str:
    """One value as a single-line YAML scalar, quoted exactly as much as it needs.

    PyYAML decides the quoting, because the rules are not worth restating: a bare
    ``2026-08-31`` is a date, a bare ``null`` is None, and a URL with a colon is fine
    unquoted only because no space follows it. Anything that comes back multi-line
    falls back to JSON, which YAML is a superset of and which is always one line.
    """
    dumped = yaml.safe_dump(
        value, default_flow_style=True, allow_unicode=True, width=10**6
    )
    scalar = dumped.replace("\n...\n", "").strip()
    return scalar if "\n" not in scalar else json.dumps(value)


def _folded_description(text: str, indent: str) -> list[str]:
    """A ``>-`` block, wrapped, the way every existing catalog entry writes prose."""
    lines = [">-"]
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > _DESCRIPTION_WIDTH:
            lines.append(f"{indent}  {current}")
            current = word
        else:
            current = candidate
    if current:
        lines.append(f"{indent}  {current}")
    return lines


def render_source_yaml_entry(
    entry: Mapping[str, Any], *, newline: str = "\n", item_indent: str = "  "
) -> str:
    """One catalog entry as YAML text, in the house style, keys in catalog order.

    The order is :data:`casesignal.drafter.templates.SOURCE_YAML_ENTRY_KEYS`; keys the
    entry carries that the constant does not name follow, sorted, so a caller adding a
    field gets it written rather than dropped.

    ``item_indent`` is read off the file being edited rather than assumed. Every
    catalog file in this repository indents its list items by two, but PyYAML's own
    default is indentless, and an entry spliced at the wrong indent is not a cosmetic
    difference: it is a file that no longer parses.
    """
    ordered = [key for key in templates.SOURCE_YAML_ENTRY_KEYS if key in entry]
    ordered += sorted(key for key in entry if key not in templates.SOURCE_YAML_ENTRY_KEYS)

    key_indent = f"{item_indent}  "
    nested_indent = f"{key_indent}  "
    lines: list[str] = []
    for position, key in enumerate(ordered):
        prefix = f"{item_indent}- " if position == 0 else key_indent
        value = entry[key]
        if key == "description" and isinstance(value, str) and value:
            head, *rest = _folded_description(value, key_indent)
            lines.append(f"{prefix}{key}: {head}")
            lines.extend(rest)
        elif isinstance(value, Mapping):
            lines.append(f"{prefix}{key}:" if value else f"{prefix}{key}: {{}}")
            lines.extend(
                f"{nested_indent}{name}: {_yaml_scalar(item)}" for name, item in value.items()
            )
        else:
            lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
    return "".join(f"{line}{newline}" for line in lines)


def append_source_yaml(path: Path, entry: dict[str, Any]) -> None:
    """Add or replace one source-catalog entry, keyed on ``adapter_name``.

    Re-drafting a source produces a new ``source_key`` (it carries the capture
    date) and the same ``adapter_name``. Keying the replacement on the key that
    changes would leave two definitions for one adapter in the catalog, and the
    pipeline resolves by ``source_key``, so the stale one stays runnable forever.

    Every line outside the replaced entry is passed through byte for byte.
    """
    adapter_name = entry.get("adapter_name")
    if not adapter_name:
        raise ScaffoldRefusal(
            "a source-catalog entry with no adapter_name cannot be replaced on a "
            "re-draft, only appended again; refusing to write one"
        )

    if not path.exists():
        _write_keeping_newlines(path, "sources:\n" + render_source_yaml_entry(entry), "\n")
        return

    text, newline = _read_keeping_newlines(path)
    lines = text.splitlines(keepends=True)
    header = next(
        (index for index, line in enumerate(lines) if _SOURCES_HEADER.match(line)), None
    )
    if header is None:
        raise ScaffoldRefusal(
            f"{path} has no top-level 'sources:' key to add an entry under; refusing to "
            f"guess at the shape of a catalog file this generator did not write"
        )

    empty = _SOURCES_HEADER.match(lines[header])
    if empty is not None and empty.group("empty"):
        # `sources: []` is a flow-style empty sequence. Splicing block items under it
        # yields a mapping key with two values and a file that does not parse, so the
        # flow marker is dropped first. The regex has always matched this form; until
        # now it matched it and then mishandled it.
        lines[header] = f"sources:{newline}"

    spans = _entry_spans(lines, header)
    indent = spans[0][2] if spans else "  "
    rendered = render_source_yaml_entry(
        entry, newline=newline, item_indent=indent
    ).splitlines(keepends=True)
    for start, stop, _ in spans:
        if _adapter_name_in(lines[start:stop]) != adapter_name:
            continue
        blanks = _trailing_blanks(lines[start:stop])
        lines[start:stop] = rendered + lines[stop - blanks : stop]
        break
    else:
        blanks = _trailing_blanks(lines)
        at = len(lines) - blanks
        if at and not lines[at - 1].endswith(("\n", "\r")):
            lines[at - 1] += newline
        separator = [newline] if spans else []
        lines[at:at] = separator + rendered

    _write_keeping_newlines(path, "".join(lines), newline)


def _entry_spans(lines: list[str], header: int) -> list[tuple[int, int, str]]:
    """(start, stop, item indent) for each list item under ``sources:``, stop-exclusive.

    An item runs to the start of the next one, so the blank line between entries
    belongs to the entry above it and is preserved when that entry is replaced. The
    indent travels with the span because a spliced entry has to match it.

    *Only at the sequence's own indent.* A catalog entry is a ``- `` line at the
    indent the FIRST entry established; a ``- `` line at any deeper indent belongs to
    something inside an entry. ``cold_case_va.yaml`` has one today::

        required_files:
          - raw_data.csv

    Matching that as an entry ended the real entry's span four lines early, so
    replacing it left ``- raw_data.csv``, ``optional_files:`` and ``metadata:``
    dangling under the new entry and the file no longer parsed. A folded description
    that wraps onto a line beginning ``- `` does the same. Both are ordinary content
    in a drafted entry a human has since edited, which is the intended lifecycle --
    and the PyYAML round-trip this splice replaced handled both correctly, so
    anything looser here is a regression, not a limitation.

    *Precondition.* The indent is seeded from the first ``- `` line found anywhere
    below the header, so this assumes ``sources:`` is the file's only top-level key --
    which it is in all twelve catalogs. A file whose ``sources:`` were empty and
    followed by another top-level key carrying a list would seed the indent from that
    other sequence. Unreachable today; stated so it stays visible if a catalog ever
    grows a second key.
    """
    starts: list[int] = []
    indent: str | None = None
    for index in range(header + 1, len(lines)):
        match = _ITEM_START.match(lines[index])
        if match is None:
            continue
        if indent is None:
            indent = match.group("indent")
        if match.group("indent") == indent:
            starts.append(index)
    if indent is None:
        return []
    return [
        (
            start,
            starts[position + 1] if position + 1 < len(starts) else len(lines),
            indent,
        )
        for position, start in enumerate(starts)
    ]


def _adapter_name_in(block: list[str]) -> str | None:
    for line in block:
        match = _ADAPTER_LINE.match(line)
        if match:
            return match.group(1)
    return None


def _trailing_blanks(block: list[str]) -> int:
    count = 0
    for line in reversed(block):
        if line.strip():
            break
        count += 1
    return count


def register_adapter(run_pipeline_path: Path, adapter_name: str, class_name: str) -> None:
    """Add the import and the ``registry.register`` call, once.

    Idempotent on ``class_name`` as a whole word: a second run over a file that
    already names the class is a no-op, and ``ColdCaseMdHowardAdapter`` does not
    count as present because ``ColdCaseMdHoward2Adapter`` is.

    The import lands in sorted position rather than at the end of the block. The
    repository lints with ruff's isort rule, so an appended import is a lint error
    on the very first CI run of a drafted adapter; the registration call lands after
    the last existing one, because that list is chronological and not sorted.
    """
    text, newline = _read_keeping_newlines(run_pipeline_path)
    if re.search(rf"\b{re.escape(class_name)}\b", text):
        return

    lines = text.splitlines(keepends=True)
    module = f"casesignal.etl.adapters.{adapter_name}.adapter"
    single = f"from {module} import {class_name}"
    import_text = (
        f"{single}{newline}"
        if len(single) <= _LINE_LENGTH
        else f"from {module} import ({newline}    {class_name},{newline}){newline}"
    )

    blocks = _adapter_import_blocks(lines)
    if blocks:
        insert_at = len(lines)
        for start, end, existing_module in blocks:
            if existing_module > module:
                insert_at = start
                break
            insert_at = end
    else:
        insert_at = _first_import_line(lines)
    lines.insert(insert_at, import_text)

    register_at = None
    indent = "    "
    for index, line in enumerate(lines):
        if _REGISTER_CALL in line:
            register_at = index + 1
            indent = line[: len(line) - len(line.lstrip())]
    if register_at is None:
        raise ScaffoldRefusal(
            f"{run_pipeline_path} holds no {_REGISTER_CALL!r} call to anchor the new "
            f"registration to; refusing to guess where the registry is built"
        )
    lines.insert(register_at, f"{indent}{_REGISTER_CALL}{class_name}){newline}")
    _write_keeping_newlines(run_pipeline_path, "".join(lines), newline)


def _adapter_import_blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    """(start, end-exclusive, module path) for every adapter import in the file."""
    blocks: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(_ADAPTER_IMPORT_PREFIX):
            module = line.split(" import ", 1)[0][len("from ") :].strip()
            end = index + 1
            if line.rstrip().endswith("("):
                while end < len(lines) and not lines[end].startswith(")"):
                    end += 1
                end = min(end + 1, len(lines))
            blocks.append((index, end, module))
            index = end
            continue
        index += 1
    return blocks


def _first_import_line(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            return index
    return 0


# --- the source-catalog entry ---


def source_yaml_entry(brief: Brief) -> dict[str, Any]:
    """The catalog entry for this draft, in the key order the existing files use."""
    year: int | None = None
    if len(brief.captured_at) >= 4 and brief.captured_at[:4].isdigit():
        year = int(brief.captured_at[:4])
    # SourceDefinition refuses a source_year that contradicts a year appearing in
    # input_path. A source whose index URL carries a year is not rare, so rather than
    # write a definition that raises on load, the year is dropped and the memo says so.
    if year is not None and (found := {int(m) for m in _YEAR.findall(brief.index_url)}):
        if year not in found:
            year = None
    return {
        "source_key": brief.source_key,
        "source_family": "cold_case",
        "adapter_name": brief.adapter_name,
        "source_code": source_code_for(brief.adapter_name, brief.state),
        "source_name": _source_name(brief),
        "input_path": brief.index_url,
        "input_type": "url",
        "source_year": year,
        "source_state": brief.state.upper(),
        "description": _description(brief),
        "required_files": [],
        "optional_files": [],
        "metadata": {
            "runtime": dict(brief.runtime),
            "source_url": brief.index_url,
            "source_release_date": brief.captured_at[:10],
            "rate_limit_seconds": _rate_limit_seconds(),
            "drafted_from_session": brief.session_id,
        },
    }


def _rate_limit_seconds() -> float:
    """The pace the capture actually ran at, read from the capture module.

    Copied here as a literal it would be a second statement of the same fact, and
    a drafted adapter that hammered a source the capture had been polite to is not
    a defect anyone would attribute to a duplicated constant.
    """
    return float(_capture._RATE_LIMIT_SECONDS)


def _source_name(brief: Brief) -> str:
    agency = brief.agency or brief.adapter_name.replace("_", " ").title()
    return f"{agency} - Cold Cases"


def _description(brief: Brief) -> str:
    return (
        f"DRAFT, generated by the SP2 Adapter Drafter from capture "
        f"{brief.session_id} on {brief.captured_at}. {brief.records_captured} record(s) "
        f"captured from a {brief.shape or 'web'} source over {brief.transport or 'http'}; "
        f"{'the listing was walked exhaustively (census)' if brief.is_census else 'a sample'}"
        f". The parse is a stub and the generated tests are red until it is written; see "
        f"docs/drafts/{brief.adapter_name}.md."
    )


# --- generated test modules ---


def render_invariant_tests(brief: Brief) -> str:
    """The structural-invariant module for one drafted adapter.

    Four assertions are always rendered, and one coverage-floor test per floor that
    can actually fail. The exact-count assertion is rendered only for a census: a
    literal record count asserted against a sampled corpus is a test that fails for
    a reason that is not the adapter's fault, and a drafter that emitted one would
    teach its operator to weaken generated tests.
    """
    census = brief.is_census
    if census:
        census_note = (
            f"The capture walked the listing exhaustively, so the number of records "
            f"the listing yields is checkable against a literal, and the assertion is "
            f"rendered below: {brief.records_captured} records out of a corpus of "
            f"{brief.records_total}."
        )
        listing_count_test = (
            "\ndef test_listing_discovery_finds_every_record(\n"
            "    listing_records: list[dict[str, Any]],\n"
            ") -> None:\n"
            '    """The capture was a census, so the corpus size is a literal.\n'
            "\n"
            f"    {brief.records_captured} record(s) captured out of a corpus of "
            f"{brief.records_total},\n"
            "    walk not truncated. A drop here is the source changing shape or the\n"
            "    listing walk losing a page, never a flaky test.\n"
            '    """\n'
            f"    found = len(listing_records)\n"
            f"    assert found == {brief.records_captured}, "
            f'f"listing discovery found {{found}}, expected {brief.records_captured}"\n'
        )
    else:
        why = _not_a_census(brief)
        census_note = (
            f"No record-count assertion is rendered here, because the listing was NOT "
            f"walked exhaustively. This capture is a sampled corpus, not a census: "
            f"{why}. An exact count asserted against a sampled corpus fails for "
            f"reasons that are not the adapter's, so the total assertion is skipped "
            f"and this paragraph stands in its place."
        )
        listing_count_test = (
            "\n# No exact-count assertion: this capture is a sampled corpus, not a\n"
            f"# census. {why}.\n"
            "# Re-capture as a census if an exact count is wanted here; do not\n"
            "# hand-write one against a sample.\n"
        )

    records_total_line = (
        f"RECORDS_TOTAL = {brief.records_total}"
        if brief.records_total is not None
        else "RECORDS_TOTAL = None  # the capture could not establish the corpus size"
    )

    return render(
        templates.INVARIANT_TESTS,
        adapter_name=brief.adapter_name,
        session_id=brief.session_id or "(unrecorded)",
        captured_at=brief.captured_at or "(unrecorded)",
        memo_path=f"docs/drafts/{brief.adapter_name}.md",
        fixtures_root=brief.fixtures_root or "(unrecorded)",
        class_name=class_name_for(brief.adapter_name),
        entries_key=_entries_key(brief.adapter_name),
        census_note=_wrapped(census_note),
        listing_count_test=listing_count_test,
        listing_fixtures=_tuple_literal(
            _fixture_names(brief.listing_paths),
            assigned_to="LISTING_FIXTURES: tuple[str, ...] = ",
        ),
        detail_fixtures=_tuple_literal(
            _fixture_names(brief.detail_paths),
            assigned_to="DETAIL_FIXTURES: tuple[str, ...] = ",
        ),
        case_type_set=_set_literal(
            templates.CASE_TYPE_VOCABULARY,
            assigned_to="CASE_TYPE_VOCABULARY = frozenset()",
        ),
        contact_markers=_tuple_literal(
            templates.CONTACT_MARKERS, assigned_to="CONTACT_MARKERS: tuple[str, ...] = "
        ),
        records_captured=brief.records_captured,
        records_total_line=records_total_line,
        source_id_strategy=brief.source_id_strategy or "unrecorded",
        coverage_floor_tests=_coverage_floor_tests(brief),
    )


def _wrapped(text: str, width: int = 78) -> str:
    """One paragraph, wrapped, so a generated docstring reads like a written one."""
    return "\n".join(textwrap.wrap(text, width=width))


def _not_a_census(brief: Brief) -> str:
    if brief.truncated:
        return "the walk was truncated with the source still offering more"
    if brief.records_total is None:
        return "the corpus size was never established"
    return (
        f"{brief.records_captured} of {brief.records_total} record(s) were captured"
    )


def _coverage_floor_tests(brief: Brief) -> str:
    """One test per floor above 0.0, and a named comment for each floor that is not.

    A floor of 0.0 renders no test at all. ``assert measured >= 0.0`` cannot fail, so
    it is not an assertion; it is a green line in a report. The inventory pass refuses
    a brief where EVERY floor is vacuous, which leaves exactly the case it cannot see:
    a mixture, where the module is red for one field and silently unchecked for three.
    """
    blocks: list[str] = []
    for name in sorted(brief.floors):
        floor = brief.floors[name]
        entry = brief.coverage.get(name, {})
        measured = entry.get("coverage")
        # The floor was measured page-scoped, so the test has to assert it over the
        # same surface. A detail-page floor asserted over the listing records is a
        # number that was never true of that denominator.
        page = brief.locators.get(name, {}).get("page") or "list"
        corpus = "detail_records" if page == "detail" else "raw_listing_records"
        if floor <= 0.0:
            blocks.append(
                f"\n# No coverage test for {name}: its derived floor is 0.0, which every\n"
                f"# parser satisfies including one that never extracts the field. A test\n"
                f"# that cannot fail reports success it did not establish, so none is\n"
                f"# rendered. Measured coverage was {_number(measured)} on the "
                f"{page} page.\n"
            )
            continue
        total = entry.get("total")
        blocks.append(
            f"\n\ndef test_coverage_floor_{_checked_field(name, 'floor')}(\n"
            f"    {corpus}: list[dict[str, Any]],\n"
            f") -> None:\n"
            f'    """{name} is carried by at least {floor:.4f} of the {page} records.\n'
            f"\n"
            f"    Measured {_number(measured)} over {_number(total)} {page} record(s)\n"
            f"    by the drafter's inventory pass. The floor was derived from that\n"
            f"    measurement, not declared by the agent that wrote the locator.\n"
            f'    """\n'
            f'    measured = _coverage({corpus}, "{name}")\n'
            f"    assert measured >= {floor:.4f}, (\n"
            f'        f"{name} coverage {{measured:.4f}} is below the measured floor '
            f'{floor:.4f} "\n'
            f'        f"over {{len({corpus})}} {page} record(s)"\n'
            f"    )\n"
        )
    return "".join(blocks) or "\n# No coverage floors were derived for this source.\n"


def render_expectation_tests(
    expectations: Sequence[ExpectedRecord], adapter_name: str
) -> str:
    """The golden-value module for one drafted adapter.

    Remaps its input into adapter vocabulary itself, using the inventory pass's own
    table. The reader writes ``victim_name``/``age``; the adapter and its raw table
    say ``case_name``/``victim_age``, and a golden test written in the reader's
    vocabulary compares against keys the adapter never produces. The remap is
    idempotent, so handing this function already-remapped records is safe.
    """
    remapped = remap_expectations(expectations)
    entries: list[str] = []
    tests: list[str] = []
    seen: set[str] = set()
    for record in remapped:
        slug = _slug(record.record_key)
        while slug in seen:
            slug = f"{slug}_x"
        seen.add(slug)
        values = "".join(
            f"        {_lit(name)}: {_lit(value)},\n"
            for name, value in sorted(record.values.items())
        )
        entries.append(f"    {_lit(record.record_key)}: {{\n{values}    }},\n")
        tests.append(
            f"\ndef test_golden_{slug}() -> None:\n"
            f'    """Every transcribed value for {record.record_key}."""\n'
            f"    key = {_lit(record.record_key)}\n"
            f"    record = _records_by_key()[key]\n"
            f"    for name, expected in EXPECTATIONS[key].items():\n"
            f"        parsed = _collapse(record.get(name))\n"
            f"        wanted = _collapse(expected)\n"
            f'        assert parsed == wanted, '
            f'f"{{key}} {{name}}: parsed {{parsed!r}}, expected {{wanted!r}}"\n'
        )
    return render(
        templates.EXPECTATION_TESTS,
        adapter_name=adapter_name,
        expectation_count=len(remapped),
        minimum_expectation_set=MINIMUM_EXPECTATION_SET,
        expectations_literal=("{\n" + "".join(entries) + "}") if entries else "{}",
        golden_tests="\n".join(tests),
    )


# --- the memo ---


def render_memo(brief: Brief) -> str:
    """The mechanically derivable half of an ingestion design doc.

    Source facts, page shapes, the measured inventory, the id strategy and the
    capture gotchas. Not the plan and not the task breakdown: those are judgements,
    and a generated file that looked like one would be read as one.
    """
    thin = len(brief.expectations) < MINIMUM_EXPECTATION_SET
    return render(
        templates.SOURCE_FACTS_MEMO,
        source_name=_source_name(brief),
        captured_at=brief.captured_at or "(unrecorded)",
        session_id=brief.session_id or "(unrecorded)",
        adapter_name=brief.adapter_name,
        source_key=brief.source_key,
        class_name=class_name_for(brief.adapter_name),
        state=brief.state,
        county=brief.county or "-",
        agency=brief.agency or "-",
        level=brief.level or "-",
        index_url=brief.index_url or "-",
        channel=brief.channel or "-",
        shape=brief.shape or "-",
        transport=brief.transport or "-",
        page_type=brief.page_type or "-",
        listing_pages=brief.listing_pages,
        pagination=_pagination(brief),
        detail_url_pattern=brief.detail_url_pattern or "none",
        dataset_id=brief.dataset_id or "-",
        robots=brief.robots or "-",
        listing_fixture_list=_inline_list(_fixture_names(brief.listing_paths)),
        detail_fixture_list=_inline_list(_fixture_names(brief.detail_paths)),
        records_captured=brief.records_captured,
        records_total="unknown" if brief.records_total is None else brief.records_total,
        listing_record_count=brief.listing_record_count,
        truncated=brief.truncated,
        record_list_identified=brief.record_list_identified,
        census_verdict="yes" if brief.is_census else "no",
        census_paragraph=_census_paragraph(brief),
        inventory_table=_inventory_table(brief),
        unreachable_count=len(brief.unreachable_floors),
        unreachable_floors=_inline_list(brief.unreachable_floors),
        vacuous_count=len(brief.vacuous_floors),
        vacuous_floors=_inline_list(brief.vacuous_floors),
        mismatch_count=len(brief.suspected_page_mismatch),
        suspected_page_mismatch=_inline_list(brief.suspected_page_mismatch),
        omission_rate=f"{brief.omission_rate:.2f}",
        omitted_count=len(brief.omitted_fields),
        requested_count=len(brief.requested_fields),
        omitted_fields=_inline_list(brief.omitted_fields),
        expectation_count=len(brief.expectations),
        expectation_thin_note=(
            f". That is below the {MINIMUM_EXPECTATION_SET} the reader pass was asked "
            f"for (first, last, most degenerate), so the generated expectation module "
            f"carries a test that is red until the reader is re-run."
            if thin
            else "."
        ),
        case_type_mix=_inline_list(brief.case_type_mix),
        case_type_vocabulary=_inline_list(templates.CASE_TYPE_VOCABULARY),
        source_id_strategy=brief.source_id_strategy or "unrecorded",
        source_id_field=brief.source_id_field or "-",
        id_paragraph=_id_paragraph(brief),
        accepted_findings=_inline_list(brief.accepted_findings),
        measured_over_unidentified_records=brief.measured_over_unidentified_records,
        fixtures_root=brief.fixtures_root or "(unrecorded)",
    )


def _census_paragraph(brief: Brief) -> str:
    if brief.is_census:
        return (
            "The listing was walked exhaustively, so the generated invariant module "
            "asserts the exact record count. A change in that number is the source "
            "changing, not the test."
        )
    return (
        f"This is a sampled corpus, not a census ({_not_a_census(brief)}), so no exact "
        f"record count is asserted anywhere. Every coverage floor below is a statement "
        f"about the records that were captured, and a page nobody captured can differ "
        f"without failing anything."
    )


def _id_paragraph(brief: Brief) -> str:
    if brief.source_id_strategy:
        return (
            f"The generated invariant module asserts uniqueness but not stability. A "
            f"`{brief.source_id_strategy}` id that renumbers when the source reorders "
            f"its listing will re-key every case on the next ingest; check that before "
            f"the first production run."
        )
    return (
        "The Scout recorded no id strategy, so the drafted adapter has nowhere to get "
        "`source_case_id` from and `prepare_input` will produce entries without one. "
        "Decide the strategy before writing the parse: a synthesised positional id is "
        "not stable across a source that reorders its listing."
    )


def _inventory_table(brief: Brief) -> str:
    names = sorted(set(brief.floors) | set(brief.coverage) | set(brief.locators))
    if not names:
        return "_No fields were measured._"
    rows = [
        "| field | page | locator kind | locator | matched/total | coverage | floor |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in names:
        locator = brief.locators.get(name, {})
        entry = brief.coverage.get(name, {})
        floor = brief.floors.get(name)
        matched = entry.get("matched")
        total = entry.get("total")
        rows.append(
            f"| `{name}` | {locator.get('page', '-')} | {locator.get('kind', '-')} | "
            f"`{locator.get('value', '-')}` | {_number(matched)}/{_number(total)} | "
            f"{_number(entry.get('coverage'))} | "
            f"{'-' if floor is None else format(floor, '.4f')} |"
        )
    return "\n".join(rows)


def _pagination(brief: Brief) -> str:
    detail = f" ({brief.pagination_detail})" if brief.pagination_detail else ""
    return f"{brief.pagination_kind}{detail}"


# --- small shared renderers ---


def _fixture_names(paths: Sequence[str]) -> tuple[str, ...]:
    return tuple(Path(path).name for path in paths)


def _tuple_literal(values: Sequence[str], *, assigned_to: str) -> str:
    """A tuple literal the formatter will leave alone.

    A one-element tuple's trailing comma is required rather than magic, so black
    collapses an exploded one back onto a line; rendering it exploded produces a
    generated file that reformats on the drafted repository's first format run.
    """
    items = [_lit(value) for value in values]
    if not items:
        return "()"
    inline = "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"
    if len(assigned_to) + len(inline) <= _LINE_LENGTH:
        return inline
    return "(\n" + "".join(f"    {item},\n" for item in items) + ")"


def _set_literal(values: Sequence[str], *, assigned_to: str) -> str:
    items = [_lit(value) for value in values]
    if not items:
        return "set()"
    inline = "{" + ", ".join(items) + "}"
    if len(assigned_to) + len(inline) <= _LINE_LENGTH:
        return inline
    return "{\n" + "".join(f"    {item},\n" for item in items) + "}"


def _inline_list(values: Sequence[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) or "none"


def _number(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


# --- the generator ---


def scaffold(brief: Brief, *, repo_root: Path) -> list[str]:
    """Write the whole draft, and return the repo-relative paths that were written.

    Every generated Python file is parsed before it is written: a module that does
    not compile is a defect in this module, and finding it here rather than in the
    drafted repository is the difference between a refusal and a broken branch.
    """
    adapter_name = brief.adapter_name
    class_name = class_name_for(adapter_name)
    memo_path = f"docs/drafts/{adapter_name}.md"
    fields = tuple(_checked_field(name, "measured field") for name in sorted(brief.floors))
    detail_note = (
        f"{len(brief.detail_paths)} detail fixture(s) were captured."
        if brief.detail_paths
        else "This capture found no detail pages, so nothing calls it yet."
    )

    common = {
        "adapter_name": adapter_name,
        "class_name": class_name,
        "source_name": _source_name(brief),
        "captured_at": brief.captured_at or "(unrecorded)",
        "session_id": brief.session_id or "(unrecorded)",
        "memo_path": memo_path,
        "entries_key": _entries_key(adapter_name),
        "log_label": _log_label(adapter_name, brief.state),
    }

    package = Path("src/casesignal/etl/adapters") / adapter_name
    rendered: list[tuple[str, str]] = [
        (
            str(package / "__init__.py"),
            render(
                templates.PACKAGE_INIT_PY,
                source_name=common["source_name"],
                captured_at=common["captured_at"],
            ),
        ),
        (
            str(package / "adapter.py"),
            render(
                templates.ADAPTER_PY,
                **common,
                index_url_literal=_lit(brief.index_url),
                runtime_spec=repr(dict(brief.runtime)),
                rate_limit_seconds=_rate_limit_seconds(),
                min_expected_basis=_min_expected_basis(brief),
                min_expected_cases=_min_expected_cases(brief),
                raw_fields=_tuple_literal(
                    fields, assigned_to="RAW_FIELDS: tuple[str, ...] = "
                ),
                locator_block=_locator_block(brief),
                detail_note=detail_note,
            ),
        ),
        (str(package / "register.py"), render(templates.REGISTER_PY, **common)),
        (
            str(package / "raw_load.py"),
            render(
                templates.RAW_LOAD_PY,
                **common,
                create_column_lines="".join(
                    f"            {name:<18} TEXT,\n" for name in fields
                ),
                insert_column_list="".join(f", {name}" for name in fields),
                insert_placeholder_list="".join(f", :{name}" for name in fields),
                insert_param_lines="".join(
                    f'                        "{name}": entry.get("{name}"),\n'
                    for name in fields
                ),
            ),
        ),
        (
            f"tests/unit/etl/adapters/test_{adapter_name}_invariants.py",
            render_invariant_tests(brief),
        ),
        (
            f"tests/unit/etl/adapters/test_{adapter_name}_expectations.py",
            render_expectation_tests(brief.expectations, adapter_name),
        ),
        (memo_path, render_memo(brief)),
    ]

    # Stamped before anything is checked, because the marker line is part of the file
    # and the parse guard has to see what actually lands.
    written = [
        (
            path,
            stamp_generated(
                body,
                path=path,
                session_id=str(common["session_id"]),
                captured_at=str(common["captured_at"]),
            ),
        )
        for path, body in rendered
    ]

    _check_before_writing(written, repo_root, adapter_name, brief.state)

    paths: list[str] = []
    for path, body in written:
        target = repo_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        paths.append(path)

    yaml_path = f"src/casesignal/etl/sources/cold_case_{brief.state.lower()}.yaml"
    append_source_yaml(repo_root / yaml_path, source_yaml_entry(brief))
    paths.append(yaml_path)

    run_pipeline = "src/casesignal/etl/runners/run_pipeline.py"
    register_adapter(repo_root / run_pipeline, adapter_name, class_name)
    paths.append(run_pipeline)
    return paths


def stamp_generated(body: str, *, path: str, session_id: str, captured_at: str) -> str:
    """Append the marker line that proves this generator wrote this exact text.

    The digest covers everything above the line. That is what makes the marker
    unforgeable by prose and, more usefully, self-invalidating: a drafted file a human
    edits stops verifying, which is precisely when it must stop being regenerated.

    The digest is UNKEYED, and the sentence has to be finished rather than left where
    it flatters the code: anyone who edits a drafted file, recomputes the SHA-256 over
    their edited body and re-stamps this line is accepted, and their file is overwritten
    on the next draft. That is by design. The threat model is accidental clobbering of
    hand-edited work, not an editor who is trying to defeat the check, and a keyed MAC
    would need a secret this generator has nowhere to keep. Forgery by prose is closed;
    forgery by deliberate re-stamping is not, and is not meant to be.
    """
    # The separator is part of what the digest covers, because `is_generated_by_us`
    # takes the head to be everything above the marker line. Two blank lines before a
    # module-level comment is what black wants after a function definition; without
    # them every generated module reformats on the drafted repository's first run.
    if path.endswith(".md"):
        opener, closer, separator = "<!-- ", " -->", "\n"
    else:
        opener, closer = "# ", ""
        separator = "\n\n" if _ends_in_a_block(body) else "\n"
    head = f"{body}{separator}"
    marker = templates.MARKER_TEMPLATE.format(
        marker=templates.GENERATED_MARKER,
        session=session_id,
        at=captured_at,
        digest=_digest(head),
    )
    return f"{head}{opener}{marker}{closer}\n"


def _ends_in_a_block(body: str) -> bool:
    """Does this module end in a def or a class, so the comment needs two blank lines?

    black's own rule, computed rather than guessed: two blank lines after a top-level
    function or class, one otherwise. A drafted ``__init__.py`` is a docstring and
    nothing else, and giving it two produced the one generated file that reformatted.
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return True  # the parse guard is about to refuse it anyway
    return bool(tree.body) and isinstance(
        tree.body[-1], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    )


def is_generated_by_us(text: str) -> bool:
    """Does this text end in our marker line, and does its digest still hold?

    False for a file we never wrote, and false for one we wrote and somebody has since
    edited. Both answers are "do not overwrite this", and the second is the one the
    substring check got wrong: a hand-edited drafted file kept its prose marker
    verbatim and was silently replaced.

    True, however, for an edited file whose editor recomputed the digest and re-stamped
    the marker. The digest is unkeyed, so this function answers "is this byte-for-byte
    what some run of this generator produced", not "has a human been here" -- see
    :func:`stamp_generated` for why that is the tradeoff and not an oversight.
    """
    lines = text.splitlines(keepends=True)
    if not lines:
        return False
    match = _MARKER_LINE.match(lines[-1].rstrip("\r\n"))
    if match is None or match.group("marker") != templates.GENERATED_MARKER:
        return False
    return match.group("digest") == _digest("".join(lines[:-1]))


def is_marker_line(line: str) -> bool:
    """Is this ONE line the generator's marker line, shape-wise?

    Deliberately weaker than :func:`is_generated_by_us`, and the two are not
    interchangeable. This answers "does this line have the marker's shape", with no
    digest verification and no statement about the file it came from; that one answers
    "is this whole text byte-for-byte something this generator produced". Use this only
    to EXCLUDE the marker from something -- a line scan, a line count -- where treating a
    forged marker as a marker costs nothing. Never use it to decide whether a file may be
    overwritten.

    It exists so that consumers which read generated files (the verify pass scans a
    drafted ``transform.py`` for marked TODOs) do not each carry their own copy of the
    marker's shape. A second copy of that pattern is a second thing to drift.
    """
    return _MARKER_LINE.match(line.rstrip("\r\n")) is not None


def _digest(body: str) -> str:
    """SHA-256 over the body, line endings normalised to LF.

    Normalised because this repository is checked out with ``core.autocrlf=true``: the
    generator writes LF, git hands back CRLF, and a digest over the raw bytes would
    then refuse to re-draft a file nobody had touched.
    """
    return hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def generated_target_paths(adapter_name: str) -> list[str]:
    """Every file :func:`scaffold` writes, by name, before a single one is rendered.

    Named separately from the rendering because the question "are these targets mine to
    write?" is decidable from the adapter name alone, and the caller who most needs the
    answer is ``claim`` -- before a source has been crawled and before a paid reader
    round. Rendering needs a measured brief; this does not.

    The two cannot drift: :func:`_check_before_writing` compares this list against the
    paths actually rendered and refuses if they disagree.
    """
    package = Path("src/casesignal/etl/adapters") / adapter_name
    return [
        str(package / "__init__.py"),
        str(package / "adapter.py"),
        str(package / "register.py"),
        str(package / "raw_load.py"),
        f"tests/unit/etl/adapters/test_{adapter_name}_invariants.py",
        f"tests/unit/etl/adapters/test_{adapter_name}_expectations.py",
        f"docs/drafts/{adapter_name}.md",
    ]


def check_existing_targets(repo_root: Path, adapter_name: str, state: str) -> None:
    """Refuse a draft whose targets are not this generator's to overwrite.

    Both refusals are facts about the operator's checkout that the adapter name and the
    state settle on their own -- nothing about the capture can change either answer --
    so they are asked at ``claim`` as well as here. A condition that cannot change
    between claim and scaffold should be named before a dollar is spent on it, which is
    what the build already did for the protected-branch check. ``run <candidate whose
    name derives to a shipped adapter>`` used to crawl the whole source and buy a full
    reader round before saying so.

    Idempotent and cheap: it reads at most eight files and writes none.
    """
    for path in generated_target_paths(adapter_name):
        target = repo_root / path
        if not target.exists():
            continue
        # Read raw. Redundant with _digest's own LF normalisation -- either alone
        # makes a CRLF checkout verify, and a mutation of this line survives because
        # of that -- but it keeps the boundary honest about what is on disk rather
        # than relying on Path.read_text's universal-newline translation to hide it.
        if is_generated_by_us(_read_keeping_newlines(target)[0]):
            continue
        raise ScaffoldRefusal(
            f"{path} already exists and is not an unmodified product of the "
            f"{templates.GENERATED_MARKER}: it carries no valid marker line, or it "
            f"carries one whose digest no longer matches its contents, which means "
            f"somebody has edited it. Overwriting it would replace that work with a "
            f"stub and leave its sibling modules importing names that no longer exist. "
            f"Move or delete it deliberately, or draft under a different adapter_name"
        )

    catalog = repo_root / f"src/casesignal/etl/sources/cold_case_{state.lower()}.yaml"
    if _catalog_entry_is_handwritten(catalog, adapter_name):
        raise ScaffoldRefusal(
            f"{catalog.name} already carries an entry for {adapter_name!r} that this "
            f"generator did not write (no 'drafted_from_session'). Replacing it would "
            f"repoint a hand-maintained source definition at a stub"
        )


def _check_before_writing(
    written: Sequence[tuple[str, str]], repo_root: Path, adapter_name: str, state: str
) -> None:
    """Everything that must hold before a single byte is written.

    Two separate refusals, both of them pre-flight so a failure leaves no half-written
    draft: a generated module that does not parse, and a target that is not an
    unmodified product of this generator.

    The second is the one with teeth. Drafting over an adapter that has since been
    written by hand replaces the real class with a stub and leaves its siblings --
    transform.py, scrape.py, a county_fips table -- importing a name that no longer
    exists, with no refusal, no warning and no backup. Obligation 5's idempotence is
    about re-running the SAME draft; this is about a draft meeting its own hand-written
    successor, which is a different event and was guarded by nothing.
    """
    for path, body in written:
        if path.endswith(".py"):
            try:
                ast.parse(body, filename=path)
            except SyntaxError as exc:  # a template defect, not a source defect
                raise ScaffoldRefusal(
                    f"the generated {path} does not parse ({exc}); refusing to write a "
                    f"draft the repository cannot import"
                ) from exc
        if not is_generated_by_us(body):
            raise ScaffoldRefusal(
                f"the body rendered for {path} does not end in a valid marker line, so "
                f"a later draft could not tell this file from a hand-written one and "
                f"would overwrite it silently. Fix the stamping, not this check"
            )

    # The list `claim` pre-flights against has to be the list this pass actually
    # writes, or hoisting the refusal forward silently stops covering a target.
    rendered_paths = [path for path, _ in written]
    declared = generated_target_paths(adapter_name)
    if rendered_paths != declared:
        raise ScaffoldRefusal(
            f"the scaffold renders {rendered_paths} but generated_target_paths declares "
            f"{declared}. `claim` pre-flights the overwrite refusal against the declared "
            f"list, so a target missing from it would be written with nothing having "
            f"checked it. Fix the declaration, not this check"
        )
    check_existing_targets(repo_root, adapter_name, state)


def _catalog_entry_is_handwritten(path: Path, adapter_name: str) -> bool:
    """Is there an entry for this adapter that the drafter did not produce?

    False when the file, the key or the entry is absent: nothing to protect. False
    when the entry carries ``drafted_from_session``, which only this generator writes.

    *Deliberately weaker than the source-file guard, and stated as a choice.* A catalog
    entry is data, not work: it is twenty lines of declarative fields with no logic in
    it, an operator editing one (a rate limit, a description) is expected rather than
    exceptional, and refusing to re-draft over a tuned ``rate_limit_seconds`` would
    make the generator unusable for the source it most needs to be re-run on. A hashed
    entry would also have to survive the surrounding file being reformatted, which the
    splice above exists precisely to allow. So the catalog check asks only "did we
    write this at all", and the file-level guard -- which fires first, because the
    package is checked before the catalog -- carries the real protection.
    """
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    header = next(
        (index for index, line in enumerate(lines) if _SOURCES_HEADER.match(line)), None
    )
    if header is None:
        return False
    for start, stop, _ in _entry_spans(lines, header):
        block = lines[start:stop]
        if _adapter_name_in(block) == adapter_name:
            return not any("drafted_from_session:" in line for line in block)
    return False


def _min_expected_cases(brief: Brief) -> int:
    """A floor 20% below what the capture saw, so ordinary churn does not trip it."""
    return max(1, int(brief.records_captured * 0.8))


def _min_expected_basis(brief: Brief) -> str:
    """The comment above the floor, wrapped so the generated file stays readable."""
    return (
        f"{brief.records_captured} record(s) at capture\n"
        f"# ({brief.captured_at or 'unknown'}); a drop past this floor means the source\n"
        f"# changed shape rather than lost a few cases"
    )


def _locator_block(brief: Brief) -> str:
    names = sorted(set(brief.floors) | set(brief.locators))
    if not names:
        return "  (none measured)"
    lines = []
    for name in names:
        locator = brief.locators.get(name, {})
        entry = brief.coverage.get(name, {})
        floor = brief.floors.get(name)
        lines.append(
            f"  {name:<16} {locator.get('page', '-'):<7} {locator.get('kind', '-'):<6} "
            f"coverage {_number(entry.get('coverage')):<7} "
            f"floor {'-' if floor is None else format(floor, '.4f')}  "
            f"{locator.get('value', '')}"
        )
    return "\n".join(lines)
