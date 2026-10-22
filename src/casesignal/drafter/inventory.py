"""The measurement pass: apply the reader's locators, count, derive the floors.

This is the deterministic half of the two-agent split described in
:mod:`casesignal.drafter.reader`. An agent supplied the semantics — which selector,
label or JSON path addresses which field. Nothing here asks an agent anything. Python
applies each locator to the captured records itself, counts how many carry a value,
and turns the count into the floor a generated adapter's test suite will assert.

*Why the floors are derived rather than declared.* A floor an agent writes is a floor
the same agent's parser is graded against, which is the parser-agrees-with-itself
failure the reader pass exists to prevent. A floor measured off the fixtures is a
statement about the source, and a parser that regresses below it fails for a reason.

*Why a wrong number is worse than no number.* Every refusal in this module exists
because the alternative is a floor that reads as success. A locator that matches
nothing would derive a floor of 0.0, which any parser satisfies. A locator measured
against records from the wrong page would derive a floor off a handful of records that
happen to be on it. An empty locator set would derive no floors at all, and
``brief.get("floors", {})`` reads that as "no floors needed". All three are refused
here, loudly, because this is the last place in the chain where the numbers and the
records they came from are both in hand.

The same rule applies to the *result*, not just the inputs. An empty ``floors`` block
and a block whose every floor is 0.0 are the same artefact to a consumer -- Task 11
renders an invariant module with no coverage test that can go red -- so
:func:`write_measured_brief` refuses both rather than writing ``inventory_measured:
true`` over them, and names which of the four routes produced it. Guarding only the
empty locator set caught one route in four.

And a locator can be wrong in a way no count reveals. A selector that matches an
element carrying nothing but a class scores full coverage for a blank cell; a locator
filed under the wrong page still matches the teasers that quote the field, scoring a
real, low number that derives a real, vacuous floor. Neither raises. Both are measured
against explicitly -- see :data:`_VALUE_ATTRIBUTES` and :func:`_better_page`.

Page scoping, specifically
--------------------------
``CapturedRecord.page`` is a **per-record** property, and an HTML capture mixes both
values by construction: every record starts on the listing, and only the detail sample
(twelve by default) is swapped to its own page. So a corpus of three hundred records
holds twelve ``"detail"`` records and the rest ``"list"``. Measuring a detail-page
locator across the whole corpus would divide twelve matches by three hundred records
and report four per cent coverage for a field the source publishes on every detail
page. A ``STRUCTURED`` field would get a misleadingly low floor; a ``NARRATIVE``
field would get ``max(0.0, 0.039 - 0.10) == 0.0``, a floor satisfied by a parser that
extracts the field never — and :class:`LocatorMatchedNothing` would not fire, because
twelve records did match.

Each locator is therefore measured against the records on **its own page**, and a
locator naming a page no record carries raises :class:`LocatorPageMismatch` rather than
:class:`LocatorMatchedNothing`. They are different bugs: the first means the locator is
pointed at a surface this capture does not hold (usually a detail-page locator on a
listing-only capture), and the fix is to re-capture; the second means the locator is
wrong, and the fix is to re-read.

That split leaves a gap, and :func:`_better_page` covers it. Neither error fires when a
mis-paged locator matches *something* on the page it was wrongly filed under, which is
the common case rather than the exotic one: a detail narrative labelled ``"list"`` still
matches the listing teasers that quote a snippet of it. So every locator is also measured
against the other pages, and a locator that does markedly better elsewhere is reported.

The two vocabularies
--------------------
The repository carries two names for the same field. SP1's field inventory calls them
``victim_name``, ``age``, ``case_number``; the adapters and their raw tables call them
``case_name``, ``victim_age``, ``source_case_id``. The reader pass emits **inventory**
names on both sides — its prompt lists the candidate's own inventory keys — and the
scaffold pass generates code and tests in **adapter** names.

:data:`ADAPTER_FIELD_NAMES` is the only mapping between them, and it covers both files:
:func:`remap_locators` for ``locators.json`` and :func:`remap_expectations` for
``expectations.json``. Everything that stays inside the SP1 contract — ``FieldSpec``
keys, the brief's ``fields`` block — keeps inventory names; everything handed to code
generation — the brief's ``floors`` and ``locators`` blocks — is remapped.

A precondition nothing here can enforce
---------------------------------------
:func:`casesignal.scout.classify.apply_verdict` rebuilds ``candidate.fields`` wholesale
from the verdict, constructing fresh :class:`FieldSpec` objects that carry no
``coverage``, ``locator`` or ``locator_kind``. Re-classifying a candidate that has
already been drafted therefore **discards every measurement this module made**, without
error and without warning. Re-run the inventory pass after any re-classification, or do
not re-classify a drafted candidate.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from bs4 import BeautifulSoup

from casesignal.drafter.capture import (
    ACCEPT_UNIDENTIFIED,
    CaptureOutcome,
    build_brief,
    write_brief,
)
from casesignal.drafter.reader import (
    ExpectedRecord,
    Locator,
    asked_fields,
    requested_fields,
)
from casesignal.drafter.shapes.base import CapturedRecord
from casesignal.scout.models import Candidate, FieldSpec, Location, LocatorKind

_logger = logging.getLogger(__name__)

# A structured field is one the source publishes as its own labelled datum, so a parser
# should retain nearly all values actually present. Multiply measured source coverage
# by this retention factor. A narrative field is extracted out of
# prose, where the measurement is the only estimate available, and the tolerance is the
# room a re-capture of a changing source is allowed to move within.
STRUCTURED_FLOOR = 0.95
NARRATIVE_TOLERANCE = 0.10

# Floors are rendered into generated test source, so they are truncated rather than
# rounded: truncation cannot lift a floor above the coverage it was derived from.
_FLOOR_PRECISION = 4

# How much better a locator has to do on a page it was NOT filed under before the
# measurement says so. Page scoping fixes the denominator; it cannot tell that the page
# on the locator is the wrong one, because a mis-paged locator that still matches
# something scores a real, low number and derives a real, low floor. Sized so a selector
# that genuinely appears on both surfaces (a listing teaser and its detail page) does not
# trip it, while one that belongs entirely to the other page does.
MISPAGED_MARGIN = 0.25

# _better_page skips the locator's own page for cost, not for correctness: a page scores
# identically to itself, so the margin below already excludes it -- but only while this
# value is non-negative. That is the assumption the skip's redundancy rests on, and an
# assumption nothing states is one nothing can falsify. It is asserted by
# test_the_mispaged_margin_is_a_non_negative_fraction rather than by a module-level
# `assert`, which python -O strips and which would make that test unable to fail.
#
# That pins the value in CI, and only there. If this ever becomes runtime-configurable --
# a brief key, an env var, a CLI flag -- the tests still pin this default while the value
# _better_page actually uses comes from somewhere else, and the redundancy argument above
# is unguarded again. Whoever makes it configurable owns re-establishing the bound.

# SP1 field-inventory name -> the name the drafted adapter and its raw table use.
#
# Identity entries are written out rather than left to the fallback so that this table
# is the complete statement of the vocabulary, and so a test can assert that its keys
# are exactly `reader.CANONICAL_FIELDS`. A name absent from here maps to itself: a
# source may publish a field SP1's canonical list never named, and inventing an adapter
# name for it here would be a guess.
ADAPTER_FIELD_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "victim_name": "case_name",
        "race": "victim_race",
        "sex": "victim_sex",
        "age": "victim_age",
        "county": "county",
        "city": "city",
        "address": "address",
        "incident_date": "incident_date",
        "case_number": "source_case_id",
        "narrative": "narrative",
        "photo": "photo",
        "contact": "contact_text",
    }
)

# Tags that end a line of rendered text. The label rule is "the rest of the line after
# the label", and in markup a line ends where a block-level element does -- not where a
# tag does, or `<strong>AGE:</strong> 34` would put the label and its value on separate
# lines and no label locator on a definition-list source would ever match.
#
# Cells are the subtlety. `<td>AGE:</td><td>34</td>` is ONE line of a rendered table, so
# `td`/`th` must NOT break: it is the row that breaks. Ending the line at every cell put
# every label alone on its own line with an empty remainder, which made LABEL locators
# unusable on tables and on definition lists -- the two commonest structured layouts, and
# the shape of AR ASP's own detail pages. That failed safe rather than producing fiction,
# but it refused a source the reader had read correctly and blamed the reader for it.
_LINE_BREAK_TAGS: frozenset[str] = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "dl",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "tfoot",
        "thead",
        "tr",
        "ul",
    }
)

# Tags that START a line without ending one. A definition list has no per-pair wrapper:
# `<dt>AGE:</dt><dd>34</dd><dt>SEX:</dt><dd>M</dd>` is four siblings, so nothing but the
# `dt` marks where one pair ends and the next begins. Breaking before each term and not
# after it puts each term on a line with its own definition, and only its own -- so a
# `dd` the source left empty yields an empty remainder rather than borrowing the next
# pair's value, which is the same false match the cell rule avoids from the other side.
_LINE_START_TAGS: frozenset[str] = frozenset({"dt"})

# Attributes that carry a value rather than describe presentation, identity or layout.
#
# `bool(element.attrs)` was too generous by a wide margin, and generous in the direction
# this module exists to prevent. A reader agent writes `td.victim-age` or `span#age`, not
# a bare `td`; on a source that leaves that cell blank the element still matches, still
# has a `class`, and so measured full coverage for a field the parser will never extract.
# The 0.95 structured floor was then met by a green test over nothing.
#
# `data-*` is NOT here, and its absence is the point. Admitting it wholesale re-opened the
# same hole through a narrower door: Bootstrap's responsive tables emit `data-label` on
# every `td`, and DataTables emits `data-order`/`data-sort` on every cell, so
# `<td class="age" data-label="Age"></td>` is a blank cell that would have counted. There
# is no convention by which a `data-` prefix means "this holds the field's value", so this
# list names the attributes that do, and nothing else. A source that hangs its value off a
# custom attribute is not measurable here, and reporting that honestly as no coverage is
# the correct outcome; inventing coverage for it is not.
_VALUE_ATTRIBUTES: frozenset[str] = frozenset(
    {"content", "data", "datetime", "href", "src", "srcset", "value"}
)


class InventoryRefusal(ValueError):
    """Base for every refusal here: a measurement that must not be trusted.

    Subclassed rather than raised directly so a caller can catch the family — "this
    draft cannot honestly be measured" — while the specific causes stay distinguishable,
    because they have different fixes.
    """


class LocatorMatchedNothing(InventoryRefusal):
    """A locator found no value in any record on its page.

    Never a coverage of zero. A zero floor is satisfied by a parser that never extracts
    the field, so the generated invariant would assert nothing while looking like it
    asserted something. The locator is wrong, or the field is not on that surface.
    """


class LocatorPageMismatch(InventoryRefusal):
    """A locator names a page this capture holds no records for.

    Distinct from :class:`LocatorMatchedNothing` on purpose. "This locator matched
    nothing anywhere" is a reader error and is fixed by re-reading; "this locator was
    measured against the wrong page" is a capture error — most often a detail-page
    locator against a capture whose detail sample was empty — and is fixed by
    re-capturing. Collapsing them sends an operator after the wrong half.
    """


class InvalidLocator(InventoryRefusal):
    """A locator that cannot be applied at all, as opposed to one that fails to match.

    A CSS selector the parser rejects, or a locator whose ``field`` disagrees with the
    key it is filed under. Both would otherwise surface as zero matches, and be reported
    as a reader that chose badly rather than as a locator that was never usable.
    """


class VocabularyCollision(InventoryRefusal):
    """Two field names collapsed onto one adapter name.

    ``case_number`` maps to ``source_case_id``; a source that also publishes a field
    literally named ``source_case_id`` would silently overwrite one with the other, and
    the survivor would be whichever came last in a dict.
    """


class NothingToMeasure(InventoryRefusal):
    """There is no measurement to make, so any brief written would be vacuous.

    Covers an empty corpus, an empty locator set, and a capture that could not say which
    of its lists held the records. Each parses cleanly, produces no floors, and reads
    downstream as "no floors needed".
    """


@dataclass(frozen=True)
class FieldCoverage:
    """How many of the records on a locator's page actually carried its field.

    ``total`` is the size of the **page-scoped** denominator, not the size of the
    corpus. For a detail-page locator against an HTML capture that is the detail sample,
    which is the only set of records where the field could have been observed at all.

    ``better_on_page`` names a page this locator did MARKEDLY better on than the one it
    was filed under, and ``better_page_coverage`` is what it scored there. Both are None
    in the ordinary case. Appended last with defaults so the four-argument positional
    construction the contract names still binds.
    """

    field: str
    matched: int
    total: int
    coverage: float
    better_on_page: str | None = None
    better_page_coverage: float | None = None


@dataclass(frozen=True)
class Measurement:
    """Everything one inventory pass established, ready for the brief.

    ``coverage`` and ``inventory`` are keyed in **inventory** vocabulary, because they
    stay inside the SP1 contract. ``floors`` and ``unreachable_floors`` are keyed in
    **adapter** vocabulary, because they are consumed by code generation.

    ``omitted`` is the half the reader pass cannot check for itself: its stray-locator
    guard refuses a locator for a field nobody asked for, but a field the inventory names
    that receives no locator passes silently, since the prompt says to omit rather than
    guess. A reader that quietly abandoned half the inventory is therefore
    indistinguishable from one that made a few careful omissions — unless somebody holds
    both halves and counts, which is what this does.

    ``unreachable_floors`` is retained for legacy brief compatibility. Current
    structured floors scale with measured source coverage. Re-capture legacy briefs
    whose fixed thresholds exceed the values actually published by the source.

    ``vacuous_floors`` is ``unreachable_floors``' mirror image, and the more dangerous of
    the two. A ``NARRATIVE`` field measured at or below the 0.10 tolerance derives a floor
    of exactly 0.0, which every parser satisfies including one that extracts the field
    never. Unlike an unreachable floor it fails nothing and says nothing: the generated
    test is green from the first run and forever. ``LocatorMatchedNothing`` correctly
    stays silent, because the locator did match something.

    ``suspected_page_mismatch`` names locators that scored markedly better on a page other
    than the one they were filed under. See :func:`_better_page`.

    ``floors_assert_nothing`` is the reason no floor in this measurement can fail, or None
    when one can. It is computed here rather than at the write boundary because this is
    where the floors still carry **inventory** names: an operator told that ``case_name``
    went vacuous would go looking for it in a ``locators.json`` that says ``victim_name``.
    """

    coverage: Mapping[str, FieldCoverage]
    floors: Mapping[str, float]
    inventory: Mapping[str, FieldSpec]
    requested: tuple[str, ...]
    omitted: tuple[str, ...]
    omission_rate: float
    unreachable_floors: tuple[str, ...]
    vacuous_floors: tuple[str, ...]
    suspected_page_mismatch: tuple[str, ...]
    floors_assert_nothing: str | None


# --- vocabulary ---


def to_adapter_field(name: str) -> str:
    """The adapter's name for one inventory field; the same name when there is no entry."""
    return ADAPTER_FIELD_NAMES.get(name, name)


def remap_locators(locators: Mapping[str, Locator]) -> dict[str, Locator]:
    """Re-key locators into adapter vocabulary, keeping ``Locator.field`` in step.

    :class:`Locator` is frozen and duplicates its own key in ``field``, so re-keying the
    dict alone leaves the two disagreeing — and ``measure`` refuses that, which is the
    only reason the disagreement would ever be noticed.
    """
    remapped: dict[str, Locator] = {}
    for name, locator in locators.items():
        adapter = to_adapter_field(name)
        if adapter in remapped:
            raise VocabularyCollision(
                f"fields {sorted({name, remapped[adapter].field})} both map to the "
                f"adapter field {adapter!r}; one locator would silently replace the other"
            )
        remapped[adapter] = replace(locator, field=adapter)
    return remapped


def remap_expectations(expectations: Sequence[ExpectedRecord]) -> list[ExpectedRecord]:
    """Re-key golden values into adapter vocabulary, one record at a time."""
    remapped: list[ExpectedRecord] = []
    for record in expectations:
        values: dict[str, str] = {}
        for name, value in record.values.items():
            adapter = to_adapter_field(name)
            if adapter in values:
                raise VocabularyCollision(
                    f"record {record.record_key!r} expects two fields that both map to "
                    f"the adapter field {adapter!r}; one golden value would replace the "
                    f"other"
                )
            values[adapter] = value
        remapped.append(ExpectedRecord(record_key=record.record_key, values=values))
    return remapped


def remap_floors(derived: Mapping[str, float]) -> dict[str, float]:
    """Re-key derived floors into adapter vocabulary, for the generated invariants."""
    remapped: dict[str, float] = {}
    for name, floor in derived.items():
        adapter = to_adapter_field(name)
        if adapter in remapped:
            raise VocabularyCollision(
                f"two fields map to the adapter field {adapter!r}, so one derived floor "
                f"would silently replace the other"
            )
        remapped[adapter] = floor
    return remapped


# --- measurement ---


def measure(
    records: Sequence[CapturedRecord], locators: Mapping[str, Locator]
) -> dict[str, FieldCoverage]:
    """Apply every locator to the records on its own page and count the hits.

    Refuses rather than returns a number nobody should act on: no records and no
    locators both produce a brief with no floors, which reads downstream as a source
    that needed none.
    """
    if not locators:
        raise NothingToMeasure(
            "no locators to measure; with none, every field goes unmeasured, no floor is "
            "derived, and the brief that results asserts nothing about the adapter"
        )
    if not records:
        raise NothingToMeasure(
            "no captured records to measure against; coverage over an empty corpus is "
            "not a low number, it is no number"
        )

    by_page: dict[str, list[CapturedRecord]] = {}
    for record in records:
        by_page.setdefault(record.page, []).append(record)

    measured: dict[str, FieldCoverage] = {}
    for name, locator in locators.items():
        if locator.field != name:
            raise InvalidLocator(
                f"locator filed under {name!r} names field {locator.field!r}; the two "
                f"identify different fields and downstream joins use one or the other"
            )
        scoped = by_page.get(locator.page)
        if not scoped:
            raise LocatorPageMismatch(
                f"locator for {name!r} names page {locator.page!r}, and this capture "
                f"holds no records from that page (it holds "
                f"{', '.join(f'{count} on {page!r}' for page, count in sorted((p, len(r)) for p, r in by_page.items()))}). "
                f"Measuring it against the records it does hold would divide hits on one "
                f"surface by the size of another. Re-capture the missing surface, or "
                f"move the locator to the page this capture reached"
            )
        matched = sum(1 for record in scoped if _matches(record, locator))
        if matched == 0:
            raise LocatorMatchedNothing(
                f"locator for {name!r} ({locator.kind.value} {locator.value!r}) matched "
                f"none of the {len(scoped)} record(s) on the {locator.page!r} page. "
                f"Coverage of zero would derive a floor of zero, which is satisfied by a "
                f"parser that never extracts the field at all"
            )
        scored = matched / len(scoped)
        rival = _better_page(by_page, locator, scored)
        if rival is not None:
            _logger.warning(
                "locator for %r is filed under page %r, where it matches %d of %d "
                "record(s) (%.3f), but matches %.3f of the %r records. A mis-paged "
                "locator that still matches something derives a real, low floor and "
                "nothing else reports it -- LocatorPageMismatch cannot, because this page "
                "does hold records. Check the locator's page before trusting its floor",
                name,
                locator.page,
                matched,
                len(scoped),
                scored,
                rival[1],
                rival[0],
            )
        measured[name] = FieldCoverage(
            field=name,
            matched=matched,
            total=len(scoped),
            coverage=scored,
            better_on_page=None if rival is None else rival[0],
            better_page_coverage=None if rival is None else rival[1],
        )
    return measured


def _better_page(
    by_page: Mapping[str, list[CapturedRecord]], locator: Locator, scored: float
) -> tuple[str, float] | None:
    """The page this locator does markedly better on than its own, if there is one.

    Page scoping fixes the denominator. It cannot tell that the page written ON the
    locator is the wrong one, and that is the gap it leaves behind: a detail-page
    narrative mislabelled ``"list"`` still matches the listing teasers that quote a
    snippet of it, so it scores a real 0.027 over 295 records, derives a real floor of
    0.0, and raises nothing -- LocatorMatchedNothing stays silent because eight records
    matched, and LocatorPageMismatch stays silent because the listing page exists.

    So the locator is measured against the other pages too and the best rival reported.
    A warning rather than a refusal: a field that genuinely appears on both surfaces is
    ordinary, the margin is a heuristic, and refusing on a heuristic would cost captures.
    """
    best: tuple[str, float] | None = None
    for page, records in by_page.items():
        # Skipping the locator's own page is a cost guard, not a correctness one: a page
        # scores identically to itself, so the margin below already excludes it. What the
        # skip saves is re-running every match over the largest bucket, which is the whole
        # of the work already done above. Deleting it changes no result, only the bill --
        # so no mutant on this line can be killed, and that is recorded rather than hidden.
        if page == locator.page or not records:
            continue
        rival = sum(1 for record in records if _matches(record, locator)) / len(records)
        if rival - scored <= MISPAGED_MARGIN:
            continue
        if best is None or rival > best[1]:
            best = (page, rival)
    return best


def floors(
    coverage: Mapping[str, FieldCoverage], inventory: Mapping[str, FieldSpec]
) -> dict[str, float]:
    """Derive the coverage floor each measured field's generated test will assert.

    ``STRUCTURED`` gets ``measured * 0.95``: require retention of 95% of the
    values the source actually supplies, rather than assuming a complete source. ``NARRATIVE`` gets ``measured - 0.10``, the
    only estimate available plus room for the source to drift. ``ABSENT`` gets nothing —
    no floor and no test — and neither does a field the inventory marks not present,
    because a floor on a field the source does not publish is coverage manufactured for
    something that is not there. Both of those are :func:`_is_ineligible`, which is where
    that rule lives; stating it here as well is how a refusal message and the floors it
    explains could drift apart without anything noticing.
    """
    derived: dict[str, float] = {}
    for name, measured in coverage.items():
        spec = inventory.get(name)
        if spec is None:
            # The vocabulary desync the reader pass guards by name: a locator keyed in
            # one vocabulary against an inventory keyed in the other measures perfectly
            # and joins onto nothing. Nothing here can repair it, but it must not pass
            # unremarked, because its only other symptom is a missing floor.
            _logger.warning(
                "measured coverage for %r, which the field inventory does not name; no "
                "floor can be derived for it and no test will be generated",
                name,
            )
            continue
        if _is_ineligible(spec):
            continue
        if spec.location is Location.STRUCTURED:
            derived[name] = _truncate(measured.coverage * STRUCTURED_FLOOR)
        else:
            derived[name] = _truncate(max(0.0, measured.coverage - NARRATIVE_TOLERANCE))
    return derived


def apply_to_inventory(
    inventory: Mapping[str, FieldSpec],
    coverage: Mapping[str, FieldCoverage],
    locators: Mapping[str, Locator],
) -> dict[str, FieldSpec]:
    """Write measured coverage and the locator that produced it onto the field specs.

    Returns new :class:`FieldSpec` objects rather than mutating the candidate's own: a
    candidate is shared across the scout registry, and a measurement written in place
    would travel to consumers that never asked for it.
    """
    updated: dict[str, FieldSpec] = {}
    for name, spec in inventory.items():
        measured = coverage.get(name)
        locator = locators.get(name)
        updated[name] = replace(
            spec,
            coverage=spec.coverage if measured is None else measured.coverage,
            locator=spec.locator if locator is None else locator.value,
            locator_kind=spec.locator_kind if locator is None else locator.kind,
        )
    return updated


def omitted_fields(candidate: Candidate, locators: Mapping[str, Locator]) -> tuple[str, ...]:
    """Fields the reader was asked to locate and did not.

    The mirror of ``run_reader``'s stray-locator check, and the half it cannot make:
    that one refuses a locator nobody asked for, this one names a request nobody
    answered. Reads :func:`casesignal.drafter.reader.asked_fields` rather than re-deriving
    what the prompt listed, so the two cannot drift; that helper is the one that folds in
    the canonical fallback, which ``requested_fields`` deliberately does not.
    """
    return tuple(sorted(set(asked_fields(candidate)) - set(locators)))


def omission_rate(candidate: Candidate, locators: Mapping[str, Locator]) -> float:
    """The fraction of the fields the prompt asked for that received no locator.

    Measured against :func:`casesignal.drafter.reader.asked_fields`, not
    :func:`~casesignal.drafter.reader.requested_fields`. The difference is the whole
    point in the case that matters most: a catalog-channel candidate arrives with no
    inventory, so ``requested_fields`` is empty and the prompt falls back to all twelve
    canonical fields. Dividing by the empty set reported an omission rate of 0.0 for a
    reader that answered one question out of twelve -- obligation 4 under-delivered
    exactly where the reader was asked the most.
    """
    # No zero guard: asked_fields returns either a non-empty present set or the whole of
    # CANONICAL_FIELDS, so the denominator cannot be zero. A guard for it would be a
    # branch no test could enter; the invariant it would lean on is asserted directly by
    # test_the_canonical_field_list_is_never_empty instead.
    return len(omitted_fields(candidate, locators)) / len(asked_fields(candidate))


def measure_capture(
    candidate: Candidate,
    records: Sequence[CapturedRecord],
    locators: Mapping[str, Locator],
) -> Measurement:
    """One whole inventory pass: measure, join, derive, and report what went unasked."""
    coverage = measure(records, locators)
    inventory = apply_to_inventory(candidate.fields, coverage, locators)
    derived = floors(coverage, inventory)
    unreachable = tuple(
        sorted(name for name, floor in derived.items() if coverage[name].coverage < floor)
    )
    if unreachable:
        _logger.warning(
            "structured field(s) %s measured below the fixed %.2f floor; the floor stands "
            "and the generated test will fail from the first run. Either the locator is "
            "wrong or the field is not as structured as the classifier recorded",
            ", ".join(unreachable),
            STRUCTURED_FLOOR,
        )
    vacuous = tuple(sorted(name for name, floor in derived.items() if floor <= 0.0))
    if vacuous:
        _logger.warning(
            "field(s) %s derived a coverage floor of 0.0, which every parser satisfies "
            "including one that never extracts them. Unlike a floor set too high this one "
            "fails nothing and reports nothing, so it is named here instead",
            ", ".join(vacuous),
        )
    omitted = omitted_fields(candidate, locators)
    if omitted:
        _logger.warning(
            "the reader left %d of %d field(s) the prompt asked for without a locator "
            "(%s); each is a field with no coverage, no floor and no generated test",
            len(omitted),
            len(asked_fields(candidate)),
            ", ".join(omitted),
        )
    mispaged = tuple(
        sorted(name for name, entry in coverage.items() if entry.better_on_page is not None)
    )
    return Measurement(
        coverage=coverage,
        floors=remap_floors(derived),
        inventory=inventory,
        requested=tuple(sorted(asked_fields(candidate))),
        omitted=omitted,
        omission_rate=omission_rate(candidate, locators),
        unreachable_floors=tuple(to_adapter_field(name) for name in unreachable),
        vacuous_floors=tuple(to_adapter_field(name) for name in vacuous),
        suspected_page_mismatch=tuple(to_adapter_field(name) for name in mispaged),
        floors_assert_nothing=_floors_assert_nothing(candidate, coverage, inventory, derived),
    )


def _floors_assert_nothing(
    candidate: Candidate,
    coverage: Mapping[str, FieldCoverage],
    inventory: Mapping[str, FieldSpec],
    derived: Mapping[str, float],
) -> str | None:
    """Why this brief's floors assert nothing, or None when at least one can fail.

    An empty ``floors`` block and a block whose every floor is 0.0 are the same artefact
    to a consumer: Task 11 renders an invariant module with no coverage test that can go
    red, and verify resolves the draft to PASS with nothing verified. The empty-locator
    guard in :func:`measure` catches only one of the routes there, so this catches the
    rest, and names which one, because "no floors" has several causes with different fixes
    and the number on disk looks identical for all of them.

    Everything here speaks **inventory** vocabulary: ``derived`` is the pre-remap floor
    map, so a vacuous ``victim_name`` is reported as ``victim_name`` and not as
    ``case_name``. An operator reading this message has ``locators.json`` and the field
    inventory in front of them, and neither of those carries an adapter name.

    The final return is not a fallback for an unexplained case. If ``derived`` is empty
    then every measured field failed :func:`floors` for exactly one of two reasons, and
    both are named, so there is nothing left over to be vague about.
    """
    if any(floor > 0.0 for floor in derived.values()):
        return None
    if derived:
        return (
            f"every derived floor is 0.0 ({', '.join(sorted(derived))}). A floor of zero "
            f"is satisfied by a parser that extracts the field never, so the generated "
            f"invariants would pass over an adapter nobody has checked. Each measured "
            f"coverage, less the {NARRATIVE_TOLERANCE:.2f} narrative tolerance, truncates "
            f"to zero at {_FLOOR_PRECISION} decimal places: check the locators before "
            f"drafting"
        )
    if not candidate.fields:
        return (
            "the candidate carries no field inventory at all, so the reader was asked for "
            "the canonical field list and every locator it returned joined onto no "
            "FieldSpec. Classify the candidate before drafting it: without an inventory "
            "there is no location to derive a floor from, and the brief would say "
            "'measured' over nothing"
        )
    if not requested_fields(candidate):
        return (
            f"the candidate's inventory marks all {len(candidate.fields)} of its fields "
            f"absent or not present, so no field is eligible for a floor. A source that "
            f"publishes nothing is not a source to draft an adapter for; re-classify it "
            f"if that verdict is wrong"
        )
    reasons: list[str] = []
    stray = sorted(set(coverage) - set(inventory))
    if stray:
        reasons.append(
            f"{', '.join(stray)} name no field the inventory carries, and it names "
            f"{', '.join(sorted(inventory))}; the locators and the inventory are in "
            f"different vocabularies, so the measurement is real and joins onto nothing"
        )
    ineligible = sorted(name for name in coverage if _is_ineligible(inventory.get(name)))
    if ineligible:
        reasons.append(
            f"{', '.join(ineligible)} name field(s) the inventory marks absent or not "
            f"present, so the reader located what the classifier said this source does "
            f"not publish. One of the two is wrong, and re-classifying the candidate "
            f"against the captured fixtures is usually the fix"
        )
    return (
        f"none of the measured field(s) ({', '.join(sorted(coverage))}) is eligible for a "
        f"floor: {'; and '.join(reasons)}"
    )


def _is_ineligible(spec: FieldSpec | None) -> bool:
    """A field the inventory carries but no floor may be derived for.

    The single expression of the eligibility rule, and it has to stay single.
    :func:`floors` skips on it and :func:`_floors_assert_nothing` explains a missing floor
    with it, and that second function's contract -- that if no floor was derived then every
    measured field is either stray or ineligible, so nothing is left unexplained -- holds
    only while the two agree. Written twice they drifted silently: a third skip reason
    added to ``floors`` would produce a refusal with a dangling colon and no diagnosis at
    all, which is a worse message than the vague one this replaced.

    ``None`` is not ineligible, it is unknown: a measured field the inventory does not name
    is the vocabulary desync, which is a different diagnosis and a different fix.
    """
    if spec is None:
        return False
    return not spec.present or spec.location is Location.ABSENT


def write_measured_brief(
    draft_dir: Path,
    candidate: Candidate,
    outcome: CaptureOutcome,
    locators: Mapping[str, Locator],
    *,
    now: str,
    adapter_name: str | None = None,
    accepted: Iterable[str] = (),
) -> tuple[Path, Measurement]:
    """Rewrite ``brief.json`` with the measurement in it, and return both.

    The capture pass writes the brief with ``inventory_measured: false``, an unmeasured
    field inventory and no ``floors`` key, explicitly relying on this pass to replace it.
    If that replacement never happens, the scaffold pass reads an unmeasured inventory
    and every floor it renders is fiction — the exact failure this pipeline exists to
    prevent, arriving through a handoff gap rather than through a bug. So the rewrite
    lives here, next to the numbers, rather than in whatever orchestrates the round.

    The brief is rebuilt through :func:`casesignal.drafter.capture.build_brief` rather
    than patched, so a field added to the brief anywhere else appears here too.

    A capture that could not identify its own record list is refused unless the operator
    named that finding, mirroring the capture pass's own policy: rows that may be filler
    objects or group wrappers make every number below a statement about the wrong things.
    """
    accepted_findings = frozenset(accepted)
    result = outcome.result
    unidentified = not result.record_list_identified
    if unidentified and ACCEPT_UNIDENTIFIED not in accepted_findings:
        raise NothingToMeasure(
            f"capture {outcome.session.session_id} could not identify which list holds "
            f"its records (basis {result.record_list_basis!r}), so the "
            f"{len(result.records)} row(s) it holds may be filler objects or group "
            f"wrappers rather than cases. Coverage over them would be a real number about "
            f"the wrong objects, and every floor derived from it would grade a parser "
            f"against a nav menu. Read the fixtures and accept the "
            f"{ACCEPT_UNIDENTIFIED!r} finding if the rows are right"
        )

    measurement = measure_capture(candidate, result.records, locators)
    # The last point at which "inventory_measured: true" can be prevented from meaning
    # nothing. Everything downstream reads the flag, not the floors.
    if measurement.floors_assert_nothing is not None:
        raise NothingToMeasure(
            f"refusing to write a measured brief for {candidate.id} whose floors assert "
            f"nothing: {measurement.floors_assert_nothing}. Written as it stands, the "
            f"brief would say inventory_measured: true over a floors block that cannot "
            f"fail, and verify would resolve the draft to PASS with nothing actually "
            f"verified"
        )
    measured = replace(candidate, fields=dict(measurement.inventory))
    brief = build_brief(
        measured,
        outcome,
        now=now,
        adapter_name=adapter_name,
        accepted=accepted_findings,
    )
    brief["inventory_measured"] = True
    brief["floors"] = dict(measurement.floors)
    brief["locators"] = {
        name: {"kind": locator.kind.value, "value": locator.value, "page": locator.page}
        for name, locator in remap_locators(locators).items()
    }
    brief["coverage"] = {
        to_adapter_field(name): {
            "matched": entry.matched,
            "total": entry.total,
            "page": locators[name].page,
            "coverage": entry.coverage,
        }
        for name, entry in measurement.coverage.items()
    }
    brief["requested_fields"] = list(measurement.requested)
    brief["omitted_fields"] = list(measurement.omitted)
    brief["omission_rate"] = measurement.omission_rate
    brief["unreachable_floors"] = list(measurement.unreachable_floors)
    brief["vacuous_floors"] = list(measurement.vacuous_floors)
    brief["suspected_page_mismatch"] = list(measurement.suspected_page_mismatch)
    brief["measured_over_unidentified_records"] = unidentified
    return (write_brief(draft_dir, brief), measurement)


# --- locator application ---


def _matches(record: CapturedRecord, locator: Locator) -> bool:
    """Does this one record carry a value for this one locator?"""
    if locator.kind is LocatorKind.CSS:
        return _css_matches(record.payload, locator)
    if locator.kind is LocatorKind.LABEL:
        return _label_matches(record.payload, locator)
    return _json_matches(record.payload, locator)


def _css_matches(payload: str, locator: Locator) -> bool:
    """The selector matches an element, and that element carries something.

    Stricter than a bare ``select_one`` is not truthy, and deliberately: an empty
    ``<td></td>`` is an element with no value, and counting it manufactures coverage for
    a field the record does not carry.

    "Carries something" means non-blank text, or a non-blank attribute that holds a value
    rather than a class or an id -- see :data:`_VALUE_ATTRIBUTES`. An ``<img src=...>`` or
    an ``<a href=...>`` is exactly how a photo or a detail link is published and neither
    has any text, so attributes have to count for something; but counting *any* attribute
    meant ``<td class="victim-age"></td>`` measured as a value, and a reader agent writes
    ``td.victim-age``, never a bare ``td``. On a source that leaves that cell blank on
    three hundred of three hundred and seven records, that scored 1.0, met the 0.95
    structured floor, and shipped a green test over a parser that extracts nothing.
    """
    try:
        element = BeautifulSoup(payload, "html.parser").select_one(locator.value)
    except Exception as exc:  # soupsieve rejects the selector; not a failure to match
        raise InvalidLocator(
            f"locator for {locator.field!r} is not a usable CSS selector "
            f"({locator.value!r}): {exc}. An unusable selector matches nothing, which "
            f"would be reported as a reader that chose badly rather than one that wrote "
            f"something no parser accepts"
        ) from exc
    if element is None:
        return False
    if element.get_text(strip=True):
        return True
    return _carries_a_value_attribute(element)


def _carries_a_value_attribute(element: Any) -> bool:
    """A non-blank attribute that holds the element's value, not its styling."""
    for name, value in element.attrs.items():
        if name not in _VALUE_ATTRIBUTES:
            continue
        # str() rather than a list/str branch: bs4 only splits the attributes it lists as
        # multi-valued (class, rel, headers and friends), none of which is a value
        # attribute, so the list case is unreachable here and a branch for it would be a
        # guard no test could enter.
        if str(value).strip():
            return True
    return False


def _label_matches(payload: str, locator: Locator) -> bool:
    """The literal label appears, with a non-empty remainder on the same line.

    Only the FIRST occurrence on a line is tried, and that is complete rather than a
    shortcut: if the label occurs again later on the same line, the first occurrence's
    remainder contains that second label, which is non-blank by construction, so the
    first occurrence has already matched. A re-search loop past it can never reach a
    case the first pass missed.
    """
    needle = locator.value.strip()
    if not needle:
        # A label locator with no label. `"".find` returns 0 on every line, and the
        # whole line becomes the "remainder", so this would match every record that has
        # any text at all -- full coverage manufactured for a field nobody located.
        raise InvalidLocator(
            f"locator for {locator.field!r} is a label locator with no label "
            f"({locator.value!r}); an empty label matches every record that has any "
            f"text, which is coverage manufactured rather than measured"
        )
    for line in _record_text(payload).splitlines():
        start = line.find(needle)
        if start != -1 and line[start + len(needle) :].strip():
            return True
    return False


def _json_matches(payload: str, locator: Locator) -> bool:
    """The dotted path walks to a leaf that is neither null nor empty.

    A payload that is not JSON at all counts as a non-match rather than an error. Page
    scoping already separates a JSON listing from the HTML detail pages beside it, and if
    *every* record on the locator's page fails to parse, :class:`LocatorMatchedNothing`
    reports it anyway.
    """
    keys = locator.value.split(".")
    if not all(key.strip() for key in keys):
        # `"a..b"` or a trailing dot. Every walk of it stops at the blank segment, so the
        # locator scores zero on every record and is reported as a reader that chose the
        # wrong path rather than one that wrote a path no walk can follow.
        raise InvalidLocator(
            f"locator for {locator.field!r} is not a usable JSON path "
            f"({locator.value!r}); it has an empty key segment, which no object can hold"
        )
    try:
        node: Any = json.loads(payload)
    except ValueError:
        return False
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return _is_a_value(node)


def _is_a_value(node: Any) -> bool:
    """Non-null, and not an empty string, list or object. ``0`` and ``False`` are values."""
    if node is None:
        return False
    if isinstance(node, str):
        return bool(node.strip())
    if isinstance(node, (list, dict)):
        return bool(node)
    return True


def _record_text(payload: str) -> str:
    """One record's rendered text, with block-level elements ending their line.

    ``get_text("\\n")`` would split ``<strong>AGE:</strong> 34`` across two lines and
    lose every label written that way; ``get_text(" ")`` would join two adjacent
    paragraphs into one line and let an empty ``COUNTY:`` borrow the next paragraph's
    text as its value. Marking the block boundaries and joining the rest with a space is
    the only one of the three that reads both correctly.

    Two sets, not one: :data:`_LINE_BREAK_TAGS` ends a line on both sides, while
    :data:`_LINE_START_TAGS` only opens one. Cells and definitions belong to neither, so
    ``<td>AGE:</td><td>34</td>`` and ``<dt>AGE:</dt><dd>34</dd>`` each render as one line
    with the label and its value on it, which is what a reader looking at the page sees.
    """
    soup = BeautifulSoup(payload, "html.parser")
    for tag in soup.find_all(list(_LINE_BREAK_TAGS)):
        tag.insert_before("\n")
        tag.insert_after("\n")
    for tag in soup.find_all(list(_LINE_START_TAGS)):
        tag.insert_before("\n")
    text: str = soup.get_text(" ")
    return text


def _truncate(value: float) -> float:
    """Truncate toward zero, so a derived floor never rises above its measurement."""
    scale: int = 10**_FLOOR_PRECISION
    return math.floor(value * scale) / scale
