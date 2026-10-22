"""The literal file bodies the scaffold pass writes, and nothing that decides.

Every template here is a whole file as it will land in the drafted repository:
an adapter package modelled on ``cold_case_ok_osbi`` (the shape a reviewer will
compare a draft against), the two generated test modules, the source-catalog
entry, and the source-facts memo. :mod:`casesignal.drafter.scaffold` owns every
decision about *which* fragments go in; this module owns *what they look like*.

*Why ``string.Template`` and not ``str.format``.* The bodies below are Python
and SQL, both of which are full of braces: an f-string, a dict literal and a
``CREATE TABLE`` all carry them, and ``str.format`` requires every one to be
doubled. Doubling several hundred braces by hand is a defect waiting to happen,
and the failure it produces is a generated module that does not parse — which
is precisely the outcome obligation 8 exists to prevent. ``$name`` collides with
nothing in Python or in the SQL used here, ``substitute`` raises ``KeyError``
on a placeholder nobody filled rather than silently emitting it, and it is
stdlib, so no dependency is added.

*Why the parse is a stub.* A drafted adapter that returned plausible records
would be graded green by its own generated tests. The stubs raise
``NotImplementedError``, so every generated test fails from the first run until
a human writes the parse, and the floors then mean something.
"""

from __future__ import annotations

from string import Template

# The generator's name, in prose and inside the marker line. It is NOT the guard:
# a substring search for it matches a hand-written file that merely mentions the
# drafter, and -- the case that actually bites -- it matches a drafted file a human
# has since edited, which is the whole intended lifecycle. Both were reproduced.
#
# The guard is :data:`MARKER_TEMPLATE`, stamped as the final line of every generated
# file with a SHA-256 over everything above it. Prose in the body cannot forge it,
# and any hand edit invalidates the digest, which is the guard's actual job: a
# drafted adapter is meant to be edited once and then to STOP being regenerated.
GENERATED_MARKER = "SP2 Adapter Drafter"

MARKER_TEMPLATE = "drafted-by: {marker}; session={session}; at={at}; sha256={digest}"

# The canonical case_type values the transform stages across the repo emit. There is
# no database constraint and no enum to import -- these are the four literals the
# existing adapters' `map_case_type` helpers return -- so the vocabulary is stated
# here, once, and rendered into the generated invariant test. A drafted source that
# needs a fifth is a deliberate edit to the generated test and to this tuple.
CASE_TYPE_VOCABULARY: tuple[str, ...] = (
    "cold_case",
    "homicide",
    "missing_person",
    "suspicious_death",
)

# Phrases that mark the start of a source's "who to call" paragraph. The generated
# contact-bleed test asserts none of them survives into a narrative, because the
# commonest silent parse defect on a block-structured listing is a narrative that
# swallowed the contact line and an extraction that then reads a detective's phone
# number as case evidence.
CONTACT_MARKERS: tuple[str, ...] = (
    "if you have any information",
    "anyone with information",
    "please contact",
)


def render(template: Template, /, **fields: object) -> str:
    """Fill one template, refusing loudly when a placeholder has no value.

    ``substitute`` rather than ``safe_substitute``: an unfilled ``$field`` left in
    generated Python is a syntax error at best and a silently wrong literal at worst,
    and this is the only place that distinction can still be made cheaply.
    """
    return template.substitute(**fields)


PACKAGE_INIT_PY = Template(
    '"""$source_name — drafted adapter package (SP2 Adapter Drafter, $captured_at)."""\n'
)


ADAPTER_PY = Template(
    '''"""$class_name — $source_name.

DRAFTED by the SP2 Adapter Drafter on $captured_at from capture session
$session_id. This file is a scaffold, not an adapter: :func:`parse_records` and
:func:`parse_detail` raise, so every generated test fails until they are written.

Source facts, page shapes, the measured field inventory and the capture gotchas
are in $memo_path. Read that before editing this file.

Measured field inventory (adapter vocabulary; coverage measured on the captured
fixtures, page-scoped):
$locator_block
"""

from __future__ import annotations

import logging
from typing import Any

from casesignal.drafter.runtime import collect, make_client
from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_definition import SourceDefinition

logger = logging.getLogger(__name__)

INDEX_URL = $index_url_literal
RUNTIME_SPEC = $runtime_spec

# The capture ran at this pace and was not blocked. Raising it is a decision about
# the source operator's bandwidth, not about this adapter's runtime.
_RATE_LIMIT_SECONDS = $rate_limit_seconds

# $min_expected_basis
_MIN_EXPECTED_CASES = $min_expected_cases

# The raw columns this adapter carries, in the adapter vocabulary the drafter
# measured. Every name here has a locator and a measured coverage in the memo.
RAW_FIELDS: tuple[str, ...] = $raw_fields

_ENTRIES_KEY = "$entries_key"


def parse_records(html: str, *, base_url: str) -> list[dict[str, Any]]:
    """One dict per case block on a listing page, in document order.

    Document order is load-bearing twice over: the generated expectation tests
    address records as ``"<listing fixture>#<index>"``, and the capture derived
    those indices from the same walk. A parse that reorders, filters or dedupes
    records silently invalidates every golden value.

    Keys should be drawn from :data:`RAW_FIELDS`; a missing field is ``None``,
    never an empty string, so coverage counts what the source actually carries.
    """
    raise NotImplementedError(
        "$adapter_name.parse_records is a drafted stub. The captured fixtures "
        "and the measured locators are in the memo; write the parse against "
        "them, then run the generated invariant and expectation tests."
    )


def parse_detail(html: str, *, url: str) -> dict[str, Any]:
    """The fields a case's own detail page carries, for a source that has one.

    Left as a stub even when the capture found no detail pages: a source that
    grows them later needs one place to put the parse, and a raise is a clearer
    marker than an empty function.
    """
    raise NotImplementedError(
        "$adapter_name.parse_detail is a drafted stub. $detail_note"
    )


def entry_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Shape one parsed record into the raw-entry dict the load stage writes."""
    return {name: record.get(name) for name in RAW_FIELDS}


class $class_name(SourceAdapter):
    """Concrete source adapter. DRAFT -- see $memo_path."""

    adapter_name = "$adapter_name"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext, *, client: Any = None,
                      detail_sample: int | None = None) -> None:
        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        meta = self.source_definition.metadata or {}
        raw_rate_limit = meta.get("rate_limit_seconds")
        rate_limit = float(raw_rate_limit if raw_rate_limit is not None else _RATE_LIMIT_SECONDS)
        index_url = str(meta.get("source_url") or INDEX_URL)

        spec = dict(RUNTIME_SPEC, index_url=index_url)
        polite = client if client is not None else make_client(spec, rate_limit)
        try:
            corpus = collect(spec, polite, parse_records, parse_detail,
                             detail_sample=detail_sample)
            records = list(corpus.records.values())
        except BaseException:
            polite.close()
            raise
        entries: list[dict[str, Any]] = [entry_from_record(record) for record in records]
        context.logger.info("$log_label prepare_input: %d entries", len(entries))

        if len(entries) < _MIN_EXPECTED_CASES:
            polite.close()
            raise RuntimeError(
                f"$log_label scrape returned only {len(entries)} cases "
                f"(< {_MIN_EXPECTED_CASES}); refusing to ingest."
            )

        context.set_metadata("polite_http", polite)
        context.set_metadata(_ENTRIES_KEY, entries)

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.$adapter_name.register import register_source

        register_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.$adapter_name.raw_load import load_raw

        load_raw(context)

    def transform(self, context: PipelineContext) -> None:
        try:
            from casesignal.etl.adapters.$adapter_name.transform import transform
            transform(context)
        finally:
            polite = context.get_metadata("polite_http")
            if polite is not None and hasattr(polite, "close"):
                try:
                    polite.close()
                except Exception:
                    pass
'''
)


REGISTER_PY = Template(
    '''"""Source registration for the $adapter_name adapter.

DRAFTED by the SP2 Adapter Drafter on $captured_at from capture session
$session_id.

source_hash = SHA256 over the canonical sorted entry payloads. Shared
registration lives in etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_ENTRIES_KEY = "$entries_key"


def register_source(context: PipelineContext) -> None:
    entries: list[dict[str, Any]] = context.get_metadata(_ENTRIES_KEY) or []
    if not entries:
        raise RuntimeError(f"{_ENTRIES_KEY} missing; prepare_input must run first.")
    definition = context.get_metadata("source_definition", {})
    source_url = definition.get("metadata", {}).get("source_url")
    register_cold_case_source(
        context,
        source_hash=canonical_entries_hash(entries),
        source_file_name=source_url,
        log_label="$log_label",
    )


def canonical_entries_hash(entries: list[dict[str, Any]]) -> str:
    canonical = [json.dumps(entry, sort_keys=True, default=str) for entry in entries]
    return hashlib.sha256("\\n".join(sorted(canonical)).encode("utf-8")).hexdigest()
'''
)


RAW_LOAD_PY = Template(
    '''"""Raw-load stage for the $adapter_name adapter.

DRAFTED by the SP2 Adapter Drafter on $captured_at from capture session
$session_id.

The column list is the measured field inventory, so a field with no locator has
no column: adding one here without a locator and a floor is how a column that is
NULL on every row ships looking like data.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.services.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

_ENTRIES_KEY = "$entries_key"


def _raw_table_name(dataset_version_id: int) -> str:
    return f"raw_cold_case.${adapter_name}_dv{dataset_version_id}"


def _ensure_table(session: Session, dataset_version_id: int) -> str:
    table = _raw_table_name(dataset_version_id)
    session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            dataset_version_id INTEGER NOT NULL,
            source_case_id     TEXT NOT NULL,
$create_column_lines            PRIMARY KEY (dataset_version_id, source_case_id)
        )
    """))
    session.commit()
    return table


def load_raw(context: PipelineContext) -> None:
    from casesignal.etl.adapters.$adapter_name.adapter import _MIN_EXPECTED_CASES

    if context.dataset_version_id is None:
        raise RuntimeError("dataset_version_id must be set before load_raw.")

    entries: list[dict[str, Any]] = context.get_metadata(_ENTRIES_KEY) or []
    if not entries:
        raise RuntimeError(f"{_ENTRIES_KEY} missing; prepare_input must run first.")

    session_factory = context.get_metadata("session_factory")
    if session_factory is not None:
        session = session_factory()
        owns_session = True
    elif context.session is not None:
        session = context.session
        owns_session = False
    else:
        raise RuntimeError(
            "$log_label raw_load requires either context.session or "
            "context.metadata['session_factory']."
        )

    dvid = context.dataset_version_id
    table = _ensure_table(session, dvid)

    inserted = 0
    failed = 0
    try:
        session.execute(text(f"DELETE FROM {table} WHERE dataset_version_id = :dv"), {"dv": dvid})
        session.commit()
        for entry in entries:
            try:
                session.execute(
                    text(f"""
                        INSERT INTO {table} (
                            dataset_version_id, source_case_id$insert_column_list
                        )
                        VALUES (
                            :dv, :source_case_id$insert_placeholder_list
                        )
                        ON CONFLICT (dataset_version_id, source_case_id) DO NOTHING
                    """),
                    {
                        "dv": dvid,
                        "source_case_id": str(entry["source_case_id"]),
$insert_param_lines                    },
                )
                inserted += 1
            except Exception as exc:
                failed += 1
                logger.warning("$log_label raw row failed: %r", exc)
        session.commit()
    finally:
        if owns_session:
            session.close()

    logger_fn = context.logger.info if context.logger is not None else logger.info
    logger_fn(
        "$log_label raw_load: inserted=%d failed=%d (of %d entries)",
        inserted,
        failed,
        len(entries),
    )
    context.increment_row_count("load_raw", inserted)

    if inserted < _MIN_EXPECTED_CASES and len(entries) >= _MIN_EXPECTED_CASES:
        raise RuntimeError(
            f"$log_label raw_load inserted only {inserted} rows out of {len(entries)}; "
            "refusing to proceed."
        )
    if failed:
        raise RuntimeError(f"$log_label raw_load had {failed} row failure(s); refusing to proceed.")
'''
)


INVARIANT_TESTS = Template(
    '''"""Structural invariants for $adapter_name, drafted from capture $session_id.

Written by the SP2 Adapter Drafter on $captured_at.

Two different claims live in this module and they are kept apart on purpose.

*Listing-level.* $census_note

*Record-level.* The detail records are a SAMPLE. Every assertion below the
listing section is a statement about the records this adapter parsed out of the
captured fixtures, not about the source's whole corpus, and a source that
changes shape on an uncaptured page will not fail here. Re-capture, do not
weaken.

The coverage floors were MEASURED off the fixtures by the drafter's inventory
pass, not declared by the agent that wrote the locators. Each is asserted over
the surface its locator was filed under, which is the only denominator the
number was ever true of. Lowering one to make a test pass is a claim about the
source and belongs in $memo_path with a reason.

Fixtures: copy the capture's fixtures into tests/fixtures/$adapter_name/ before
running this module. The capture left them under $fixtures_root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from casesignal.etl.adapters.$adapter_name.adapter import (
    INDEX_URL,
    RUNTIME_SPEC,
    parse_detail,
    parse_records,
)

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "$adapter_name"

LISTING_FIXTURES: tuple[str, ...] = $listing_fixtures

DETAIL_FIXTURES: tuple[str, ...] = $detail_fixtures

CASE_TYPE_VOCABULARY = frozenset($case_type_set)

CONTACT_MARKERS: tuple[str, ...] = $contact_markers

RECORDS_CAPTURED = $records_captured
$records_total_line


def _listing_records() -> list[dict[str, Any]]:
    from casesignal.drafter.runtime import replay
    return list(replay(FIXTURES_ROOT, RUNTIME_SPEC, parse_records, parse_detail).records.values())


def _detail_records() -> list[dict[str, Any]]:
    from casesignal.drafter.runtime import replay
    return replay(FIXTURES_ROOT, RUNTIME_SPEC, parse_records, parse_detail).details


@pytest.fixture(scope="module")
def listing_records() -> list[dict[str, Any]]:
    return _listing_records()


@pytest.fixture(scope="module")
def raw_listing_records() -> list[dict[str, Any]]:
    from casesignal.drafter.runtime import replay
    return replay(FIXTURES_ROOT, RUNTIME_SPEC, parse_records, parse_detail).listings


@pytest.fixture(scope="module")
def detail_records() -> list[dict[str, Any]]:
    return _detail_records()


def _coverage(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    carried = sum(1 for record in records if str(record.get(field) or "").strip())
    return carried / len(records)


# --- listing-level invariants (the listing was walked exhaustively) ---

$listing_count_test

# --- record-level invariants (over the parsed records, which are a sample) ---


def test_every_record_has_a_case_name(listing_records: list[dict[str, Any]]) -> None:
    """A record with no name is a parse that matched a wrapper, not a case."""
    assert listing_records, "the parse produced no records at all"
    nameless = [
        index
        for index, record in enumerate(listing_records)
        if not str(record.get("case_name") or "").strip()
    ]
    assert not nameless, f"records at {nameless} carry no case_name"


def test_source_case_ids_are_unique(listing_records: list[dict[str, Any]]) -> None:
    """Duplicate ids collapse cases at load: the raw table's PK silently drops them.

    id strategy recorded by the capture: $source_id_strategy
    """
    ids = [record.get("source_case_id") for record in listing_records]
    assert all(ids), "every record needs a source_case_id before load_raw runs"
    assert len(set(ids)) == len(ids), "source_case_id collides across records"


def test_case_types_are_in_the_vocabulary(listing_records: list[dict[str, Any]]) -> None:
    """An unmapped label falls through to 'cold_case' and loses the source's own type."""
    strays = sorted(
        {
            str(record.get("case_type"))
            for record in listing_records
            if record.get("case_type") is not None
            and record.get("case_type") not in CASE_TYPE_VOCABULARY
        }
    )
    assert not strays, f"case_type values outside the vocabulary: {strays}"


def test_contact_line_does_not_bleed_into_narrative(
    listing_records: list[dict[str, Any]],
) -> None:
    """A narrative that swallowed the tip line feeds a phone number to the extractor."""
    bled: list[int] = []
    for index, record in enumerate(listing_records):
        narrative = str(record.get("narrative") or "").lower()
        if any(marker in narrative for marker in CONTACT_MARKERS):
            bled.append(index)
            continue
        contact = str(record.get("contact_text") or "").strip()
        if contact and contact.lower() in narrative:
            bled.append(index)
    assert not bled, f"records at {bled} carry the contact line inside the narrative"


def test_runtime_replays_captured_requests() -> None:
    from types import SimpleNamespace
    import logging
    from casesignal.drafter.runtime import ReplayClient, replay
    from casesignal.etl.adapters.$adapter_name.adapter import $class_name

    client = ReplayClient(FIXTURES_ROOT)
    metadata: dict[str, Any] = {}
    context = SimpleNamespace(logger=logging.getLogger(__name__),
                              set_metadata=lambda key, value: metadata.update({key: value}))
    adapter = $class_name(SimpleNamespace(metadata={}))
    adapter.prepare_input(context, client=client,
                          detail_sample=client.manifest["detail_sample"])
    expected = replay(FIXTURES_ROOT, RUNTIME_SPEC, parse_records, parse_detail)
    entries = metadata["$entries_key"]
    assert len(entries) == len(expected.records)
    assert [r.get("source_case_id") for r in entries] == [
        r.get("source_case_id") for r in expected.records.values()]
    assert set(client.requested) == set(client.fixtures)


def test_canonical_mapping_and_transform_wiring() -> None:
    import ast
    import inspect
    from datetime import date
    from casesignal.drafter.runtime import replay
    from casesignal.etl.adapters.$adapter_name import transform as module
    from casesignal.etl.adapters.$adapter_name.adapter import $class_name
    from types import SimpleNamespace

    corpus = replay(FIXTURES_ROOT, RUNTIME_SPEC, parse_records, parse_detail)
    canonical = [module.to_case(dict(record)) for record in corpus.records.values()]
    assert canonical
    for raw, row in zip(corpus.records.values(), canonical):
        assert row["case_name"] and row["source_case_id"]
        assert row["case_type"] in CASE_TYPE_VOCABULARY
        if raw.get("incident_date"):
            date.fromisoformat(str(row["incident_date"]))
    assert len({r["source_case_id"] for r in canonical}) == len(canonical)
    stage = ast.parse(inspect.getsource(module.transform))
    assert not any(isinstance(n, ast.Pass) or (
        isinstance(n, ast.Name) and n.id == "NotImplementedError") for n in ast.walk(stage))
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "to_case" for n in ast.walk(stage)), "transform must use to_case"
    called: list[object] = []
    original = module.transform
    try:
        module.transform = lambda context: called.append(context)
        context = SimpleNamespace(get_metadata=lambda key: None)
        $class_name(SimpleNamespace(metadata={})).transform(context)
        assert called == [context]
    finally:
        module.transform = original


# --- measured coverage floors ---
$coverage_floor_tests'''
)


EXPECTATION_TESTS = Template(
    '''"""Golden values for $adapter_name, transcribed off the captured fixtures.

Written by the SP2 Adapter Drafter.

Each key of :data:`EXPECTATIONS` is a capture record key, ``"<fixture>#<index>"``.
The fixture named is always the LISTING fixture the record was discovered on,
even where the value was read off that record's own detail page -- the capture
assigns a record its key during the listing walk and keeps it. So the lookup
below replays the captured fetch graph, joins sampled details using their actual
URLs, and enumerates listings in document order. A parse
that reorders or filters records will fail
``test_every_expected_record_key_resolves`` rather than quietly compare the
wrong case.

Values are the source's own strings, compared after whitespace collapse and
nothing else. A drafted adapter that normalises a date or a name will fail here,
and that is the intended conversation: normalisation belongs in transform, and
the memo should say so.

Fixtures: copy the capture's fixtures into tests/fixtures/$adapter_name/.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from casesignal.etl.adapters.$adapter_name.adapter import RUNTIME_SPEC, parse_records, parse_detail

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "$adapter_name"

# The reader was asked for the first record, the last record, and the most
# degenerate one it could find. That instruction is not enforceable by a loader,
# so the count it actually produced is recorded here and asserted below: a run
# that transcribed one easy record would otherwise render one green golden test
# and read exactly like a run that did the job.
EXPECTED_RECORD_COUNT = $expectation_count
MINIMUM_EXPECTATION_SET = $minimum_expectation_set

EXPECTATIONS: dict[str, dict[str, str]] = $expectations_literal


def _collapse(value: object) -> str:
    return " ".join(str(value or "").split())


@lru_cache(maxsize=1)
def _records_by_key() -> dict[str, dict[str, Any]]:
    """Re-derive the capture's record keys from the listing fixtures."""
    from casesignal.drafter.runtime import replay
    return replay(FIXTURES_ROOT, RUNTIME_SPEC, parse_records, parse_detail).records


def test_the_expectation_set_is_not_thin() -> None:
    """Fails from the first run when the reader transcribed fewer than three records.

    Red on a draft, deliberately. The same convention the drafter uses for a
    structural floor measured below its fixed value: a generated test that cannot
    fail is worse than one that fails for a stated reason.
    """
    assert EXPECTED_RECORD_COUNT >= MINIMUM_EXPECTATION_SET, (
        f"only {EXPECTED_RECORD_COUNT} golden record(s) were transcribed for "
        f"$adapter_name; the reader pass was asked for at least "
        f"{MINIMUM_EXPECTATION_SET} (first, last, and the most degenerate record "
        f"in the capture). Re-run the reader before trusting this module."
    )


def test_every_expected_record_key_resolves() -> None:
    """The keys address records this parse actually produces, in the same order."""
    if not EXPECTATIONS:
        return
    available = _records_by_key()
    missing = sorted(set(EXPECTATIONS) - set(available))
    assert not missing, (
        f"record key(s) {missing} address no parsed record. Keys are "
        f"'<listing fixture>#<index in document order>'; a parse that filters, "
        f"dedupes or reorders records breaks them."
    )

$golden_tests'''
)


# The catalog entry's key order, in the order every existing cold_case_*.yaml uses.
# :func:`casesignal.drafter.scaffold.source_yaml_entry` builds the mapping and
# :func:`casesignal.drafter.scaffold.render_source_yaml_entry` renders it in this
# order; a test asserts the two agree, because a second independent statement of a
# key order is a thing that drifts with nothing noticing.
SOURCE_YAML_ENTRY_KEYS: tuple[str, ...] = (
    "source_key",
    "source_family",
    "adapter_name",
    "source_code",
    "source_name",
    "input_path",
    "input_type",
    "source_year",
    "source_state",
    "description",
    "required_files",
    "optional_files",
    "metadata",
)


SOURCE_FACTS_MEMO = Template(
    """# $source_name — source facts

**DRAFT.** Written by the SP2 Adapter Drafter on $captured_at from capture
session `$session_id`. Everything below is mechanically derived from the
capture and the measurement: it is the half of an ingestion design doc that can
be read off the source. The plan, the task breakdown and the ingest run-book are
not here and are not derivable — write them next to this file.

## Identity

| | |
|---|---|
| adapter_name | `$adapter_name` |
| source_key | `$source_key` |
| class | `$class_name` |
| state | $state |
| county | $county |
| agency | $agency |
| agency level | $level |
| index URL | $index_url |

## Page shapes

| | |
|---|---|
| channel | $channel |
| capture shape | $shape |
| transport | $transport |
| page type | $page_type |
| listing pages walked | $listing_pages |
| pagination | $pagination |
| detail URL pattern | $detail_url_pattern |
| dataset id | $dataset_id |
| robots | $robots |

Listing fixtures: $listing_fixture_list

Detail fixtures: $detail_fixture_list

## Corpus

| | |
|---|---|
| records captured | $records_captured |
| corpus size (records_total) | $records_total |
| listing record count | $listing_record_count |
| truncated | $truncated |
| record list identified | $record_list_identified |
| census | $census_verdict |

$census_paragraph

## Measured field inventory

Coverage is page-scoped: the denominator is the records on the surface the
locator was filed under, not the whole corpus. Floors are derived, not declared
— `STRUCTURED` fields take `measured * 0.95` and narrative fields take
`measured - 0.10` — and the generated invariant module asserts them.

$inventory_table

## Advisory findings

These four come out of the inventory pass and nothing else consumes them. They
are not failures; each is a reason a green generated test may mean less than it
looks like it means.

- **Unreachable floors** ($unreachable_count): $unreachable_floors
  Legacy briefs may contain a fixed floor above the measured source coverage.
  Re-capture those briefs; current structured floors scale with measured coverage.
- **Vacuous floors** ($vacuous_count): $vacuous_floors
  A floor of 0.0, satisfied by a parser that never extracts the field. No
  coverage test is generated for these — a test that cannot fail is worse than
  no test, because it reports success.
- **Suspected page mismatch** ($mismatch_count): $suspected_page_mismatch
  Locators that scored markedly better on a surface other than the one they were
  filed under. Usually a listing teaser selector filed as a detail locator.
- **Omission rate**: $omission_rate -- $omitted_count of the $requested_count
  fields the reader was asked for received no locator, namely $omitted_fields.
  A field with no locator has no coverage, no floor and no generated test, and
  nothing upstream refuses it: the prompt says to omit rather than guess.

## Expectations

$expectation_count golden record(s) were transcribed$expectation_thin_note

## Case types

Case-type mix recorded by the Scout: $case_type_mix

The generated invariant test asserts every parsed `case_type` is one of
$case_type_vocabulary. A source that publishes a fifth type needs both the
transform mapping and that test's vocabulary widened, in one change.

## Id strategy

| | |
|---|---|
| strategy | $source_id_strategy |
| field | $source_id_field |

$id_paragraph

## Capture gotchas

- The generated parse stubs raise `NotImplementedError`. Every generated test is
  red until the parse is written; that is the scaffold working, not a bug.
- Record keys in the expectation module are `<listing fixture>#<index>` and the
  index is document order on the LISTING page, even for values read off a detail
  page. A parse that filters or reorders records invalidates every golden value.
- The capture allowlisted exactly one host and passed no robots bypass. If this
  source needs `CASESIGNAL_BYPASS_ROBOTS_HOSTS` or a TLS impersonation
  transport, that is a per-source operator decision and belongs in the run-book,
  not in this adapter's defaults.
- Accepted capture findings: $accepted_findings
- Measured over unidentified records: $measured_over_unidentified_records
- Copy the capture fixtures from `$fixtures_root` into
  `tests/fixtures/$adapter_name/` before running the generated tests.
"""
)
