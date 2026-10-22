"""Tests for the inventory pass: applying locators, counting, deriving floors.

Every refusal in the module under test exists because the alternative is a number
that reads as success, so most of these tests assert on a refusal rather than on a
value. The measurement tests all pin the *denominator* as well as the numerator: the
denominator is where a page-mixed corpus turns a healthy field into a zero floor, and
a test that only checks ``matched`` would not see it move.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from casesignal.drafter import capture as cap
from casesignal.drafter import inventory as inv
from casesignal.drafter import reader, session
from casesignal.drafter.reader import ExpectedRecord, Locator
from casesignal.drafter.shapes.base import CapturedRecord, CaptureResult
from casesignal.scout.models import (
    Candidate,
    Channel,
    FieldSpec,
    Level,
    Location,
    LocatorKind,
    Page,
)

RECORDS = [
    CapturedRecord(
        key="r1", payload="<p><strong>AGE:</strong> 34</p><p>COUNTY: Tulsa</p>", page="detail"
    ),
    CapturedRecord(key="r2", payload="<p><strong>AGE:</strong> 51</p>", page="detail"),
    CapturedRecord(key="r3", payload="<p>no fields here</p>", page="detail"),
]
LOCATORS = {
    "victim_age": Locator("victim_age", LocatorKind.CSS, "strong", "detail"),
    "county": Locator("county", LocatorKind.LABEL, "COUNTY:", "detail"),
}


# --- the brief's own contract ---


def test_measure_reports_matched_over_total() -> None:
    coverage = inv.measure(RECORDS, LOCATORS)
    assert coverage["victim_age"].matched == 2
    assert coverage["victim_age"].total == 3
    assert coverage["victim_age"].coverage == pytest.approx(2 / 3)
    assert coverage["county"].matched == 1


def test_measure_raises_when_a_locator_matches_nothing() -> None:
    locators = {"weapon": Locator("weapon", LocatorKind.LABEL, "WEAPON:", "detail")}
    with pytest.raises(inv.LocatorMatchedNothing, match="weapon"):
        inv.measure(RECORDS, locators)


def test_json_path_locator_reads_nested_keys() -> None:
    records = [
        CapturedRecord(key="r1", payload='{"attributes": {"CASE_NO": "A1"}}', page="list"),
        CapturedRecord(key="r2", payload='{"attributes": {}}', page="list"),
    ]
    locators = {
        "case_number": Locator("case_number", LocatorKind.JSON_PATH, "attributes.CASE_NO", "list")
    }
    coverage = inv.measure(records, locators)
    assert coverage["case_number"].coverage == 0.5


def test_floors_use_95_percent_for_structured_and_a_tolerance_for_narrative() -> None:
    coverage = {
        "victim_age": inv.FieldCoverage("victim_age", 3, 3, 1.0),
        "county": inv.FieldCoverage("county", 4, 10, 0.4),
    }
    spec = {
        "victim_age": FieldSpec(present=True, location=Location.STRUCTURED),
        "county": FieldSpec(present=True, location=Location.NARRATIVE),
    }
    assert inv.floors(coverage, spec) == {"victim_age": 0.95, "county": pytest.approx(0.30)}


def test_absent_fields_get_no_floor() -> None:
    coverage = {"race": inv.FieldCoverage("race", 0, 5, 0.0)}
    spec = {"race": FieldSpec(present=False, location=Location.ABSENT)}
    assert inv.floors(coverage, spec) == {}


def test_apply_to_inventory_writes_coverage_and_locator_onto_field_specs() -> None:
    spec = {"victim_age": FieldSpec(present=True, location=Location.STRUCTURED)}
    coverage = {"victim_age": inv.FieldCoverage("victim_age", 2, 3, 2 / 3)}
    updated = inv.apply_to_inventory(spec, coverage, LOCATORS)
    assert updated["victim_age"].coverage == pytest.approx(2 / 3)
    assert updated["victim_age"].locator == "strong"
    assert updated["victim_age"].locator_kind is LocatorKind.CSS


# --- page scoping: the measurement that decides whether a floor is real ---


def _mixed_corpus(detail_sample: int, total: int) -> list[CapturedRecord]:
    """A capture shaped the way ``shapes/html`` shapes one: mostly list, a detail sample."""
    records = []
    for index in range(total):
        if index < detail_sample:
            records.append(
                CapturedRecord(
                    key=f"listing_1.html#{index}",
                    payload="<p>NARRATIVE: last seen leaving work</p>",
                    page="detail",
                )
            )
        else:
            records.append(
                CapturedRecord(
                    key=f"listing_1.html#{index}", payload="<p>ANN ADAMS</p>", page="list"
                )
            )
    return records


def test_a_detail_locator_is_measured_against_the_detail_records_only() -> None:
    # The obligation this module exists for. Unscoped, a field on every one of twelve
    # detail pages measures 12/307; scoped, it measures 12/12.
    records = _mixed_corpus(detail_sample=12, total=307)
    locators = {
        "narrative": Locator("narrative", LocatorKind.LABEL, "NARRATIVE:", "detail"),
    }
    coverage = inv.measure(records, locators)
    assert coverage["narrative"].total == 12
    assert coverage["narrative"].coverage == 1.0


def test_a_narrative_floor_survives_a_page_mixed_corpus() -> None:
    # Same corpus, run all the way through to the floor. Unscoped this is
    # max(0.0, 12/307 - 0.10) == 0.0, a floor any parser satisfies.
    records = _mixed_corpus(detail_sample=12, total=307)
    locators = {"narrative": Locator("narrative", LocatorKind.LABEL, "NARRATIVE:", "detail")}
    inventory = {"narrative": FieldSpec(present=True, location=Location.NARRATIVE)}
    coverage = inv.measure(records, locators)
    assert inv.floors(coverage, inventory) == {"narrative": pytest.approx(0.90)}


def test_a_list_locator_is_measured_against_the_records_still_on_the_listing() -> None:
    records = _mixed_corpus(detail_sample=12, total=307)
    locators = {"victim_name": Locator("victim_name", LocatorKind.CSS, "p", "list")}
    coverage = inv.measure(records, locators)
    assert coverage["victim_name"].total == 295
    assert coverage["victim_name"].matched == 295


def test_a_locator_naming_a_page_the_capture_never_reached_is_a_page_mismatch() -> None:
    # Distinct from LocatorMatchedNothing: the locator may be perfect, and the fix is a
    # re-capture rather than a re-read.
    records = [CapturedRecord(key="r1", payload="<p>COUNTY: Tulsa</p>", page="list")]
    locators = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "detail")}
    with pytest.raises(inv.LocatorPageMismatch, match="detail"):
        inv.measure(records, locators)


def test_a_page_mismatch_is_not_a_matched_nothing() -> None:
    records = [CapturedRecord(key="r1", payload="<p>COUNTY: Tulsa</p>", page="list")]
    locators = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "detail")}
    with pytest.raises(inv.InventoryRefusal) as caught:
        inv.measure(records, locators)
    assert not isinstance(caught.value, inv.LocatorMatchedNothing)


def test_the_page_mismatch_message_names_the_pages_the_capture_does_hold() -> None:
    records = [CapturedRecord(key="r1", payload="<p>x</p>", page="list")]
    locators = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "detail")}
    with pytest.raises(inv.LocatorPageMismatch, match="1 on 'list'"):
        inv.measure(records, locators)


# --- refusals ---


def test_measure_refuses_an_empty_locator_set() -> None:
    with pytest.raises(inv.NothingToMeasure, match="no locators"):
        inv.measure(RECORDS, {})


def test_measure_refuses_an_empty_corpus() -> None:
    with pytest.raises(inv.NothingToMeasure, match="empty corpus"):
        inv.measure([], LOCATORS)


def test_measure_refuses_a_locator_whose_field_disagrees_with_its_key() -> None:
    # Locator is frozen and duplicates its key in `field`; a remap that re-keys the dict
    # without dataclasses.replace leaves the two naming different fields.
    locators = {"age": Locator("victim_age", LocatorKind.CSS, "strong", "detail")}
    with pytest.raises(inv.InvalidLocator, match="victim_age"):
        inv.measure(RECORDS, locators)


def test_measure_refuses_a_css_selector_the_parser_rejects() -> None:
    locators = {"county": Locator("county", LocatorKind.CSS, "p[", "detail")}
    with pytest.raises(inv.InvalidLocator, match="usable CSS selector"):
        inv.measure(RECORDS, locators)


# --- locator application, kind by kind ---


def test_a_css_match_on_an_element_with_no_text_and_no_attributes_is_not_a_value() -> None:
    records = [
        CapturedRecord(key="r1", payload="<p><span>Tulsa</span></p>", page="list"),
        CapturedRecord(key="r2", payload="<p><span></span></p>", page="list"),
    ]
    locators = {"county": Locator("county", LocatorKind.CSS, "span", "list")}
    assert inv.measure(records, locators)["county"].matched == 1


def test_a_css_match_on_an_element_carrying_only_attributes_is_a_value() -> None:
    # A photo is an <img src=...> with no text at all; requiring text would report the
    # field as absent on a source that publishes it on every record.
    records = [CapturedRecord(key="r1", payload='<div><img src="a.jpg"></div>', page="list")]
    locators = {"photo": Locator("photo", LocatorKind.CSS, "img", "list")}
    assert inv.measure(records, locators)["photo"].coverage == 1.0


def test_a_label_needs_a_non_empty_remainder_on_its_own_line() -> None:
    records = [
        CapturedRecord(key="r1", payload="<p>COUNTY: Tulsa</p>", page="list"),
        CapturedRecord(key="r2", payload="<p>COUNTY:</p><p>Tulsa</p>", page="list"),
    ]
    locators = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "list")}
    assert inv.measure(records, locators)["county"].matched == 1


def test_a_label_inside_an_inline_tag_keeps_its_value_on_the_same_line() -> None:
    # The common markup for a labelled field. get_text("\n") would split these.
    records = [CapturedRecord(key="r1", payload="<p><strong>AGE:</strong> 34</p>", page="list")]
    locators = {"age": Locator("age", LocatorKind.LABEL, "AGE:", "list")}
    assert inv.measure(records, locators)["age"].coverage == 1.0


def test_a_label_repeated_on_one_line_matches_on_the_first_occurrence() -> None:
    # There is no re-search past the first occurrence, and there cannot need to be: the
    # first occurrence's remainder contains the second label, which is non-blank by
    # construction, so the first occurrence has always already matched. A mutant that
    # deleted a re-search loop here survived, which is how the loop was found to be dead.
    records = [CapturedRecord(key="r1", payload="<p>AGE: AGE: 34</p>", page="list")]
    locators = {"age": Locator("age", LocatorKind.LABEL, "AGE:", "list")}
    assert inv.measure(records, locators)["age"].coverage == 1.0


def test_measure_refuses_a_label_locator_with_no_label() -> None:
    # An empty needle finds index 0 on every line and takes the whole line as its
    # remainder, so it would report full coverage for a field nobody located.
    locators = {"county": Locator("county", LocatorKind.LABEL, "   ", "detail")}
    with pytest.raises(inv.InvalidLocator, match="no label"):
        inv.measure(RECORDS, locators)


def test_measure_refuses_a_json_path_with_an_empty_segment() -> None:
    records = [CapturedRecord(key="r1", payload='{"a": {"b": "x"}}', page="list")]
    locators = {"county": Locator("county", LocatorKind.JSON_PATH, "a..b", "list")}
    with pytest.raises(inv.InvalidLocator, match="usable JSON path"):
        inv.measure(records, locators)


def test_a_json_path_leaf_that_is_null_or_blank_is_not_a_value() -> None:
    records = [
        CapturedRecord(key="r1", payload='{"a": {"b": "x"}}', page="list"),
        CapturedRecord(key="r2", payload='{"a": {"b": null}}', page="list"),
        CapturedRecord(key="r3", payload='{"a": {"b": "   "}}', page="list"),
        CapturedRecord(key="r4", payload='{"a": {"b": []}}', page="list"),
    ]
    locators = {"county": Locator("county", LocatorKind.JSON_PATH, "a.b", "list")}
    assert inv.measure(records, locators)["county"].matched == 1


def test_a_json_path_leaf_of_zero_is_a_value() -> None:
    records = [CapturedRecord(key="r1", payload='{"a": {"b": 0}}', page="list")]
    locators = {"age": Locator("age", LocatorKind.JSON_PATH, "a.b", "list")}
    assert inv.measure(records, locators)["age"].coverage == 1.0


def test_a_json_path_through_a_non_object_does_not_match() -> None:
    # r3 is why the guard tests isinstance rather than just `key not in node`: `"b" in 5`
    # is a TypeError, raised out of a measurement pass that has no business crashing on
    # a source that publishes a number where the path expected an object.
    records = [
        CapturedRecord(key="r1", payload='{"a": {"b": "x"}}', page="list"),
        CapturedRecord(key="r2", payload='{"a": "not an object"}', page="list"),
        CapturedRecord(key="r3", payload='{"a": 5}', page="list"),
    ]
    locators = {"county": Locator("county", LocatorKind.JSON_PATH, "a.b", "list")}
    assert inv.measure(records, locators)["county"].matched == 1


def test_a_json_path_against_a_payload_that_is_not_json_does_not_match() -> None:
    records = [
        CapturedRecord(key="r1", payload='{"a": {"b": "x"}}', page="list"),
        CapturedRecord(key="r2", payload="<html>not json</html>", page="list"),
    ]
    locators = {"county": Locator("county", LocatorKind.JSON_PATH, "a.b", "list")}
    assert inv.measure(records, locators)["county"].matched == 1


# --- floors ---


def test_a_narrative_floor_never_goes_below_zero() -> None:
    coverage = {"county": inv.FieldCoverage("county", 1, 100, 0.01)}
    spec = {"county": FieldSpec(present=True, location=Location.NARRATIVE)}
    assert inv.floors(coverage, spec) == {"county": 0.0}


def test_a_derived_floor_never_rises_above_its_measurement() -> None:
    coverage = {"county": inv.FieldCoverage("county", 2, 3, 2 / 3)}
    spec = {"county": FieldSpec(present=True, location=Location.NARRATIVE)}
    derived = inv.floors(coverage, spec)["county"]
    assert derived <= 2 / 3 - 0.10
    assert derived == pytest.approx(0.5666, abs=1e-4)


def test_an_absent_location_gets_no_floor_even_when_the_field_is_marked_present() -> None:
    # The brief's own absent test pairs present=False with ABSENT, so it passes on the
    # `present` clause alone and never executes the location clause. This one does.
    coverage = {"race": inv.FieldCoverage("race", 5, 5, 1.0)}
    spec = {"race": FieldSpec(present=True, location=Location.ABSENT)}
    assert inv.floors(coverage, spec) == {}


def test_a_field_the_inventory_marks_not_present_gets_no_floor() -> None:
    # Distinct from the ABSENT check: present=False with a structured location is
    # contradictory, and a 0.95 floor on a field the source does not publish is
    # manufactured coverage.
    coverage = {"race": inv.FieldCoverage("race", 5, 5, 1.0)}
    spec = {"race": FieldSpec(present=False, location=Location.STRUCTURED)}
    assert inv.floors(coverage, spec) == {}


def test_one_eligibility_rule_governs_both_the_floors_and_the_diagnosis() -> None:
    # floors() and the refusal's diagnosis stated the same rule twice, and the refusal's
    # contract -- that a missing floor is always explained by exactly one of stray or
    # ineligible -- held only while they agreed. Nothing asserted that, and a third skip
    # reason in floors() would have produced a refusal with a dangling colon and no
    # diagnosis at all. Both now read _is_ineligible, and this pins the rule itself across
    # the whole matrix rather than pinning that the two happen to agree.
    locators = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "detail")}
    table = [
        (True, Location.STRUCTURED, True),
        (True, Location.NARRATIVE, True),
        (True, Location.ABSENT, False),
        (False, Location.STRUCTURED, False),
        (False, Location.NARRATIVE, False),
        (False, Location.ABSENT, False),
    ]
    for present, location, eligible in table:
        candidate = _candidate(county=FieldSpec(present=present, location=location))
        measurement = inv.measure_capture(candidate, RECORDS, locators)
        assert bool(measurement.floors) is eligible, (present, location)
        assert (measurement.floors_assert_nothing is None) is eligible, (present, location)


def test_a_measured_field_the_inventory_does_not_name_gets_no_floor_and_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coverage = {"victim_age": inv.FieldCoverage("victim_age", 3, 3, 1.0)}
    with caplog.at_level("WARNING"):
        assert inv.floors(coverage, {"age": FieldSpec(present=True)}) == {}
    assert "victim_age" in caplog.text


# --- apply_to_inventory ---


def test_apply_to_inventory_leaves_the_candidates_own_specs_untouched() -> None:
    spec = FieldSpec(present=True, location=Location.STRUCTURED)
    inventory = {"victim_age": spec}
    coverage = {"victim_age": inv.FieldCoverage("victim_age", 2, 3, 2 / 3)}
    inv.apply_to_inventory(inventory, coverage, LOCATORS)
    assert spec.coverage is None
    assert spec.locator is None


def test_apply_to_inventory_keeps_a_field_that_was_never_measured() -> None:
    inventory = {
        "victim_age": FieldSpec(present=True, location=Location.STRUCTURED),
        "weapon": FieldSpec(present=True, location=Location.NARRATIVE),
    }
    coverage = {"victim_age": inv.FieldCoverage("victim_age", 2, 3, 2 / 3)}
    updated = inv.apply_to_inventory(inventory, coverage, LOCATORS)
    assert set(updated) == {"victim_age", "weapon"}
    assert updated["weapon"].coverage is None
    assert updated["weapon"].locator is None


# --- vocabulary ---


def test_the_mapping_covers_exactly_the_canonical_inventory_fields() -> None:
    assert set(inv.ADAPTER_FIELD_NAMES) == set(reader.CANONICAL_FIELDS)


def test_the_mapping_carries_the_three_names_that_actually_differ() -> None:
    assert inv.to_adapter_field("victim_name") == "case_name"
    assert inv.to_adapter_field("age") == "victim_age"
    assert inv.to_adapter_field("case_number") == "source_case_id"


def test_a_field_the_mapping_does_not_name_maps_to_itself() -> None:
    assert inv.to_adapter_field("weapon") == "weapon"


def test_remap_locators_rekeys_the_dict_and_the_locators_own_field() -> None:
    remapped = inv.remap_locators({"age": Locator("age", LocatorKind.CSS, "strong", "detail")})
    assert set(remapped) == {"victim_age"}
    assert remapped["victim_age"].field == "victim_age"
    assert remapped["victim_age"].value == "strong"


def test_remap_locators_refuses_two_fields_that_collapse_onto_one_adapter_name() -> None:
    locators = {
        "case_number": Locator("case_number", LocatorKind.CSS, "a", "list"),
        "source_case_id": Locator("source_case_id", LocatorKind.CSS, "b", "list"),
    }
    with pytest.raises(inv.VocabularyCollision, match="source_case_id"):
        inv.remap_locators(locators)


def test_remap_expectations_rekeys_the_golden_values() -> None:
    remapped = inv.remap_expectations(
        [ExpectedRecord("listing_1.html#0", {"victim_name": "Ann Example", "age": "34"})]
    )
    assert remapped[0].record_key == "listing_1.html#0"
    assert remapped[0].values == {"case_name": "Ann Example", "victim_age": "34"}


def test_remap_expectations_refuses_a_collision_inside_one_record() -> None:
    expectations = [ExpectedRecord("listing_1.html#0", {"age": "34", "victim_age": "35"})]
    with pytest.raises(inv.VocabularyCollision, match="victim_age"):
        inv.remap_expectations(expectations)


def test_remap_floors_rekeys_into_adapter_vocabulary() -> None:
    assert inv.remap_floors({"age": 0.95, "county": 0.3}) == {"victim_age": 0.95, "county": 0.3}


def test_remap_floors_refuses_a_collision() -> None:
    with pytest.raises(inv.VocabularyCollision, match="victim_age"):
        inv.remap_floors({"age": 0.95, "victim_age": 0.5})


# --- omission ---


def _candidate(**fields: FieldSpec) -> Candidate:
    return Candidate(
        id="ok-osbi",
        level=Level.STATE,
        state="OK",
        index_url="https://osbi.ok.gov/cold-cases",
        channel=Channel.WEB,
        fields=dict(fields),
    )


def test_omitted_fields_names_requested_fields_that_received_no_locator() -> None:
    candidate = _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED, page=Page.DETAIL),
        county=FieldSpec(present=True, location=Location.NARRATIVE, page=Page.DETAIL),
        narrative=FieldSpec(present=True, location=Location.NARRATIVE, page=Page.DETAIL),
    )
    locators = {"age": Locator("age", LocatorKind.CSS, "strong", "detail")}
    assert inv.omitted_fields(candidate, locators) == ("county", "narrative")
    assert inv.omission_rate(candidate, locators) == pytest.approx(2 / 3)


def test_omission_ignores_fields_the_inventory_marks_absent() -> None:
    # Reads reader.requested_fields rather than re-deriving the present-only filter, so
    # an absent field is never counted as an omission.
    candidate = _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED),
        race=FieldSpec(present=False, location=Location.ABSENT),
    )
    locators = {"age": Locator("age", LocatorKind.CSS, "strong", "detail")}
    assert inv.omitted_fields(candidate, locators) == ()
    assert inv.omission_rate(candidate, locators) == 0.0


def test_omission_is_measured_against_the_canonical_fallback_when_there_is_no_inventory() -> None:
    # A catalog-channel candidate arrives with no inventory, so the prompt asks for all
    # twelve CANONICAL_FIELDS. Dividing by requested_fields (empty) reported 0.0 for a
    # reader that answered one question in twelve.
    candidate = _candidate()
    locators = {"age": Locator("age", LocatorKind.CSS, "strong", "detail")}
    assert set(inv.omitted_fields(candidate, locators)) == set(reader.CANONICAL_FIELDS) - {"age"}
    assert inv.omission_rate(candidate, locators) == pytest.approx(11 / 12)


def test_the_canonical_field_list_is_never_empty() -> None:
    # omission_rate divides by len(asked_fields(...)) with no zero guard, which is safe
    # only while this holds. Asserted rather than guarded, so it is falsifiable.
    assert reader.CANONICAL_FIELDS
    assert reader.asked_fields(_candidate())


def test_omission_uses_the_readers_own_asked_fields_helper() -> None:
    # Both halves read reader.asked_fields, so the canonical fallback is expressed once.
    assert set(inv.omitted_fields(_candidate(), {})) == set(reader.asked_fields(_candidate()))


def test_the_reader_prompt_asks_for_exactly_the_asked_fields() -> None:
    candidate = _candidate()
    prompt = reader.build_reader_prompt(candidate, ["listing_1.html"], Path("out"))
    for name in reader.asked_fields(candidate):
        assert f"  - {name}" in prompt


def test_omission_uses_the_same_filter_the_reader_prompt_used() -> None:
    candidate = _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED),
        race=FieldSpec(present=False, location=Location.ABSENT),
    )
    assert set(inv.omitted_fields(candidate, {})) == set(reader.requested_fields(candidate))


# --- measure_capture ---


def _measurable_candidate() -> Candidate:
    return _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED, page=Page.DETAIL),
        county=FieldSpec(present=True, location=Location.NARRATIVE, page=Page.DETAIL),
        narrative=FieldSpec(present=True, location=Location.NARRATIVE, page=Page.DETAIL),
    )


_MEASURABLE_LOCATORS = {
    "age": Locator("age", LocatorKind.CSS, "strong", "detail"),
    "county": Locator("county", LocatorKind.LABEL, "COUNTY:", "detail"),
}


def test_measure_capture_reports_floors_in_adapter_vocabulary() -> None:
    measurement = inv.measure_capture(
        _measurable_candidate(), RECORDS, dict(_MEASURABLE_LOCATORS)
    )
    assert set(measurement.floors) == {"victim_age", "county"}
    assert measurement.floors["victim_age"] == pytest.approx(0.6333)


def test_measure_capture_keeps_the_inventory_in_inventory_vocabulary() -> None:
    measurement = inv.measure_capture(
        _measurable_candidate(), RECORDS, dict(_MEASURABLE_LOCATORS)
    )
    assert set(measurement.inventory) == {"age", "county", "narrative"}
    assert measurement.inventory["age"].coverage == pytest.approx(2 / 3)


def test_measure_capture_reports_the_omission_rate() -> None:
    measurement = inv.measure_capture(
        _measurable_candidate(), RECORDS, dict(_MEASURABLE_LOCATORS)
    )
    assert measurement.omitted == ("narrative",)
    assert measurement.omission_rate == pytest.approx(1 / 3)
    assert measurement.requested == ("age", "county", "narrative")


def test_measure_capture_scales_structured_floor_to_source_coverage() -> None:
    measurement = inv.measure_capture(
        _measurable_candidate(), RECORDS, dict(_MEASURABLE_LOCATORS)
    )
    # Preserve 95% of the values actually available in the captured source.
    assert measurement.floors["victim_age"] == pytest.approx(0.6333)
    assert measurement.inventory["age"].coverage == pytest.approx(2 / 3)
    assert measurement.unreachable_floors == ()


def test_measure_capture_reports_no_unreachable_floor_when_the_measurement_meets_it() -> None:
    records = [
        CapturedRecord(key="r1", payload="<p><strong>AGE:</strong> 34</p>", page="detail"),
        CapturedRecord(key="r2", payload="<p><strong>AGE:</strong> 51</p>", page="detail"),
    ]
    candidate = _candidate(age=FieldSpec(present=True, location=Location.STRUCTURED))
    measurement = inv.measure_capture(
        candidate, records, {"age": Locator("age", LocatorKind.CSS, "strong", "detail")}
    )
    assert measurement.unreachable_floors == ()


# --- the brief rewrite ---


def _outcome(**over: Any) -> cap.CaptureOutcome:
    result = CaptureResult(
        listing_paths=["listing_1.html"],
        detail_paths=["detail_1.html"],
        records=list(RECORDS),
        records_captured=3,
        records_total=3,
        pagination_kind="single",
        **over,
    )
    return cap.CaptureOutcome(
        result=result,
        session=session.CaptureSession(
            session_id="20260831T140211Z-a3f9", shape="html", started_at="2026-08-31T14:02:11Z"
        ),
        shape="html",
    )


def _brief(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_write_measured_brief_flips_the_measured_flag(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    assert _brief(path)["inventory_measured"] is True


def test_the_capture_pass_leaves_the_brief_unmeasured(tmp_path: Path) -> None:
    # The state this pass exists to replace. If it never runs, the scaffold pass reads
    # this and every floor it renders is fiction.
    brief = cap.build_brief(_measurable_candidate(), _outcome(), now="2026-08-31T14:02:11Z")
    assert brief["inventory_measured"] is False
    assert "floors" not in brief
    assert brief["fields"]["age"]["coverage"] is None


def test_write_measured_brief_carries_the_derived_floors(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    assert _brief(path)["floors"] == {"victim_age": pytest.approx(0.6333), "county": pytest.approx(0.2333, abs=1e-4)}


def test_write_measured_brief_populates_the_field_inventory(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    fields = _brief(path)["fields"]
    assert fields["age"]["coverage"] == pytest.approx(2 / 3)
    assert fields["age"]["locator"] == "strong"
    assert fields["age"]["locator_kind"] == "css"


def test_write_measured_brief_records_what_the_reader_omitted(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    brief = _brief(path)
    assert brief["omitted_fields"] == ["narrative"]
    assert brief["omission_rate"] == pytest.approx(1 / 3)
    assert brief["requested_fields"] == ["age", "county", "narrative"]


def test_write_measured_brief_records_the_locators_in_adapter_vocabulary(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    locators = _brief(path)["locators"]
    assert set(locators) == {"victim_age", "county"}
    assert locators["victim_age"] == {"kind": "css", "value": "strong", "page": "detail"}


def test_write_measured_brief_records_the_page_scoped_denominator(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    assert _brief(path)["coverage"]["victim_age"] == {
        "matched": 2,
        "total": 3,
        "page": "detail",
        "coverage": pytest.approx(2 / 3),
    }


def test_write_measured_brief_does_not_mutate_the_candidate(tmp_path: Path) -> None:
    candidate = _measurable_candidate()
    inv.write_measured_brief(
        tmp_path,
        candidate,
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    assert candidate.fields["age"].coverage is None


def test_write_measured_brief_refuses_a_capture_that_never_identified_its_records(
    tmp_path: Path,
) -> None:
    # Task 6's own probe captured six hundred {"pad": n} objects this way. Coverage over
    # them is a real number about the wrong objects.
    with pytest.raises(inv.NothingToMeasure, match="identify which list"):
        inv.write_measured_brief(
            tmp_path,
            _measurable_candidate(),
            _outcome(record_list_identified=False),
            dict(_MEASURABLE_LOCATORS),
            now="2026-08-31T14:02:11Z",
        )


def test_write_measured_brief_honours_an_accepted_unidentified_finding(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(record_list_identified=False),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
        accepted=[cap.ACCEPT_UNIDENTIFIED],
    )
    brief = _brief(path)
    assert brief["measured_over_unidentified_records"] is True
    assert brief["accepted_findings"] == [cap.ACCEPT_UNIDENTIFIED]


def test_write_measured_brief_marks_an_ordinary_capture_as_identified(tmp_path: Path) -> None:
    path, _ = inv.write_measured_brief(
        tmp_path,
        _measurable_candidate(),
        _outcome(),
        dict(_MEASURABLE_LOCATORS),
        now="2026-08-31T14:02:11Z",
    )
    assert _brief(path)["measured_over_unidentified_records"] is False


def test_write_measured_brief_overwrites_the_unmeasured_brief_in_place(tmp_path: Path) -> None:
    outcome = _outcome()
    candidate = _measurable_candidate()
    first = cap.write_brief(
        tmp_path, cap.build_brief(candidate, outcome, now="2026-08-31T14:02:11Z")
    )
    second, _ = inv.write_measured_brief(
        tmp_path, candidate, outcome, dict(_MEASURABLE_LOCATORS), now="2026-08-31T14:02:11Z"
    )
    assert first == second
    assert _brief(second)["inventory_measured"] is True


def test_write_measured_brief_keeps_the_capture_briefs_own_keys(tmp_path: Path) -> None:
    # Rebuilt through build_brief rather than patched, so nothing the capture pass
    # records is dropped by this rewrite.
    outcome = _outcome()
    candidate = _measurable_candidate()
    unmeasured = cap.build_brief(candidate, outcome, now="2026-08-31T14:02:11Z")
    path, _ = inv.write_measured_brief(
        tmp_path, candidate, outcome, dict(_MEASURABLE_LOCATORS), now="2026-08-31T14:02:11Z"
    )
    assert set(unmeasured) <= set(_brief(path))


# --- the precondition this module cannot enforce ---


def test_reclassifying_a_drafted_candidate_discards_the_measurement() -> None:
    # Documented in the module docstring and reproduced here so the day it changes,
    # something says so. scout.classify.apply_verdict rebuilds candidate.fields
    # wholesale, and the rebuilt FieldSpecs carry no coverage.
    from casesignal.scout.classify import apply_verdict

    candidate = _measurable_candidate()
    measurement = inv.measure_capture(candidate, RECORDS, dict(_MEASURABLE_LOCATORS))
    measured = replace(candidate, fields=dict(measurement.inventory))
    assert measured.fields["age"].coverage is not None

    apply_verdict(
        measured,
        {
            "gates": {"cold_homicide": "pass", "official_first_party": "pass"},
            "fields": {"age": {"present": True, "location": "structured"}},
        },
    )
    assert measured.fields["age"].coverage is None


# --- C2: an element that matches but carries no value ---


def _css_matched(payload: str, selector: str) -> bool:
    records = [
        CapturedRecord(key="r1", payload=payload, page="list"),
        CapturedRecord(key="r2", payload='<p><span class="x">Tulsa</span></p>', page="list"),
    ]
    locators = {"county": Locator("county", LocatorKind.CSS, selector, "list")}
    return inv.measure(records, locators)["county"].matched == 2


def test_an_empty_element_with_only_a_class_is_not_a_value() -> None:
    # The commonest shape by far: a reader writes `td.victim-age`, never a bare `td`.
    # Counting any attribute made a blank cell measure as full coverage, meet the 0.95
    # structured floor, and ship a green test over a parser that extracts nothing.
    assert not _css_matched('<table><tr><td class="age"></td></tr></table>', "td, span")


def test_an_empty_element_with_only_an_id_is_not_a_value() -> None:
    assert not _css_matched('<p><span id="age"></span></p>', "span")


def test_a_whitespace_only_element_with_a_class_is_not_a_value() -> None:
    assert not _css_matched('<table><tr><td class="age">   </td></tr></table>', "td, span")


def test_an_image_source_is_a_value() -> None:
    assert _css_matched('<div><img class="photo" src="a.jpg"></div>', "img, span")


def test_a_link_href_is_a_value() -> None:
    assert _css_matched('<div><a class="d" href="/case/1"></a></div>', "a, span")


def test_a_bootstrap_responsive_table_label_is_not_a_value() -> None:
    # Bootstrap emits data-label on EVERY td of a responsive table, so admitting data-*
    # wholesale re-opened C2 through a narrower door: a blank cell with a class the reader
    # selected on and a framework data-label would have measured as full coverage.
    assert not _css_matched(
        '<table><tr><td class="age" data-label="Age"></td></tr></table>', "td, span"
    )


def test_a_datatables_sort_key_is_not_a_value() -> None:
    assert not _css_matched(
        '<table><tr><td class="age" data-sort="0"></td></tr></table>', "td, span"
    )
    assert not _css_matched(
        '<table><tr><td class="age" data-order="0"></td></tr></table>', "td, span"
    )


def test_a_test_hook_attribute_is_not_a_value() -> None:
    assert not _css_matched('<div><b class="age" data-testid="age"></b></div>', "b, span")


def test_a_custom_data_attribute_is_not_a_value_either() -> None:
    # Deliberate, and the honest cost of the fix: there is no convention by which a
    # `data-` prefix means "this holds the field's value", so a source that hangs its
    # value there measures as no coverage. Reporting that is correct; inventing coverage
    # for it, and being wrong on every Bootstrap table, is not.
    assert not _css_matched('<div><b class="age" data-age="34"></b></div>', "b, span")


def test_presentation_and_accessibility_attributes_are_not_values() -> None:
    assert not _css_matched('<div><b class="age" style="color:red"></b></div>', "b, span")
    assert not _css_matched('<div><b class="age" aria-label="Age"></b></div>', "b, span")


def test_a_blank_value_attribute_is_not_a_value() -> None:
    assert not _css_matched('<div><img class="photo" src="   "></div>', "img, span")


def test_a_multi_valued_class_is_still_not_a_value() -> None:
    # bs4 hands `class` back as a list. It is not a value attribute either way, which is
    # why the list/str branch that used to sit in _carries_a_value_attribute was
    # unreachable: no value attribute is one bs4 splits.
    assert not _css_matched('<div><span class="a b c"></span></div>', "span")


# --- I3: labels on tables and definition lists ---


def _label_matched(payload: str, label: str) -> int:
    records = [CapturedRecord(key="r1", payload=payload, page="list")]
    locators = {"age": Locator("age", LocatorKind.LABEL, label, "list")}
    try:
        return inv.measure(records, locators)["age"].matched
    except inv.LocatorMatchedNothing:
        return 0


def test_a_label_in_a_table_cell_finds_its_value_in_the_next_cell() -> None:
    # A row is one rendered line; the cell is not. AR ASP's detail pages are label:value
    # rows, and ending the line at every cell made LABEL locators unusable on them.
    assert _label_matched("<table><tr><td>AGE:</td><td>34</td></tr></table>", "AGE:") == 1


def test_a_label_in_a_table_cell_with_an_empty_value_cell_does_not_match() -> None:
    assert _label_matched("<table><tr><td>AGE:</td><td></td></tr></table>", "AGE:") == 0


def test_a_table_row_does_not_borrow_the_next_rows_value() -> None:
    payload = "<table><tr><td>AGE:</td><td></td></tr><tr><td>COUNTY:</td><td>Tulsa</td></tr></table>"
    assert _label_matched(payload, "AGE:") == 0


def test_a_definition_term_finds_its_definition() -> None:
    assert _label_matched("<dl><dt>AGE:</dt><dd>34</dd></dl>", "AGE:") == 1


def test_a_definition_term_with_an_empty_definition_does_not_match() -> None:
    # A dt opens a line without closing one, so a pair cannot borrow the next pair's
    # value the way a flat get_text(" ") would let it.
    payload = "<dl><dt>AGE:</dt><dd></dd><dt>COUNTY:</dt><dd>Tulsa</dd></dl>"
    assert _label_matched(payload, "AGE:") == 0


def test_a_definition_list_still_separates_its_pairs() -> None:
    payload = "<dl><dt>AGE:</dt><dd>34</dd><dt>COUNTY:</dt><dd>Tulsa</dd></dl>"
    assert _label_matched(payload, "COUNTY:") == 1


# --- I4: a locator filed under the wrong page ---


def _mispaged_corpus() -> list[CapturedRecord]:
    """OSBI-shaped: 295 listing teasers, 8 of which quote the narrative, 12 detail pages."""
    records = [
        CapturedRecord(
            key=f"listing_1.html#{i}", payload="<p>NARRATIVE: last seen leaving work</p>",
            page="detail",
        )
        for i in range(12)
    ]
    for i in range(12, 307):
        carries = i < 20  # eight teasers quote a snippet
        payload = "<p>NARRATIVE: last seen</p>" if carries else "<p>ANN ADAMS</p>"
        records.append(CapturedRecord(key=f"listing_1.html#{i}", payload=payload, page="list"))
    return records


def test_a_mispaged_locator_that_still_matches_something_is_reported() -> None:
    # The gap page scoping leaves behind: LocatorMatchedNothing stays silent because eight
    # records matched, and LocatorPageMismatch stays silent because the listing exists.
    locators = {"narrative": Locator("narrative", LocatorKind.LABEL, "NARRATIVE:", "list")}
    entry = inv.measure(_mispaged_corpus(), locators)["narrative"]
    assert entry.coverage == pytest.approx(8 / 295, abs=1e-4)
    assert entry.better_on_page == "detail"
    assert entry.better_page_coverage == 1.0


def test_a_mispaged_locator_warns(caplog: pytest.LogCaptureFixture) -> None:
    locators = {"narrative": Locator("narrative", LocatorKind.LABEL, "NARRATIVE:", "list")}
    with caplog.at_level("WARNING"):
        inv.measure(_mispaged_corpus(), locators)
    assert "mis-paged" in caplog.text


def test_a_field_that_scores_the_same_on_both_pages_is_not_reported_as_mispaged() -> None:
    records = _mixed_corpus(detail_sample=12, total=307)
    locators = {"victim_name": Locator("victim_name", LocatorKind.CSS, "p", "list")}
    assert inv.measure(records, locators)["victim_name"].better_on_page is None


def test_a_field_that_does_modestly_better_elsewhere_stays_inside_the_margin() -> None:
    # The test above pins only "not strictly better", because both pages score 1.0 there
    # -- a mutant reducing the margin comparison to `rival <= scored` survived it. This
    # one puts the rival ABOVE the scored page but below MISPAGED_MARGIN, which is the
    # only arrangement the margin itself decides.
    records = [
        CapturedRecord(
            key=f"d{i}",
            payload="<p>COUNTY: Tulsa</p>" if i < 9 else "<p>nothing</p>",
            page="detail",
        )
        for i in range(10)
    ]
    records += [
        CapturedRecord(
            key=f"l{i}",
            payload="<p>COUNTY: Tulsa</p>" if i < 8 else "<p>nothing</p>",
            page="list",
        )
        for i in range(10)
    ]
    locators = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "list")}
    entry = inv.measure(records, locators)["county"]
    assert entry.coverage == pytest.approx(0.8)  # 0.9 on detail: better, but by 0.1
    assert entry.better_on_page is None


def test_a_correctly_paged_locator_is_not_reported_as_mispaged() -> None:
    locators = {"narrative": Locator("narrative", LocatorKind.LABEL, "NARRATIVE:", "detail")}
    assert inv.measure(_mispaged_corpus(), locators)["narrative"].better_on_page is None


def test_measure_capture_surfaces_the_suspected_page_mismatch() -> None:
    candidate = _candidate(
        narrative=FieldSpec(present=True, location=Location.NARRATIVE, page=Page.LIST),
    )
    locators = {"narrative": Locator("narrative", LocatorKind.LABEL, "NARRATIVE:", "list")}
    measurement = inv.measure_capture(candidate, _mispaged_corpus(), locators)
    assert measurement.suspected_page_mismatch == ("narrative",)


# --- I1: a floor of zero asserts nothing ---


def _thin_corpus() -> list[CapturedRecord]:
    """Ten records, one of which carries the field: coverage 0.1, floor exactly 0.0."""
    records = [CapturedRecord(key="r0", payload="<p>COUNTY: Tulsa</p>", page="list")]
    records += [
        CapturedRecord(key=f"r{i}", payload="<p>nothing</p>", page="list") for i in range(1, 10)
    ]
    return records


_THIN_LOCATORS = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "list")}


def test_a_narrative_floor_of_exactly_zero_is_reported_as_vacuous() -> None:
    candidate = _candidate(county=FieldSpec(present=True, location=Location.NARRATIVE))
    measurement = inv.measure_capture(candidate, _thin_corpus(), dict(_THIN_LOCATORS))
    assert measurement.floors == {"county": 0.0}
    assert measurement.vacuous_floors == ("county",)


def test_a_vacuous_floor_warns(caplog: pytest.LogCaptureFixture) -> None:
    candidate = _candidate(county=FieldSpec(present=True, location=Location.NARRATIVE))
    with caplog.at_level("WARNING"):
        inv.measure_capture(candidate, _thin_corpus(), dict(_THIN_LOCATORS))
    assert "0.0" in caplog.text


def test_a_floor_that_can_fail_is_not_reported_as_vacuous() -> None:
    measurement = inv.measure_capture(
        _measurable_candidate(), RECORDS, dict(_MEASURABLE_LOCATORS)
    )
    assert measurement.vacuous_floors == ()


# --- C1: a measured brief whose floors assert nothing ---


def _thin_outcome(records: list[CapturedRecord]) -> cap.CaptureOutcome:
    outcome = _outcome()
    return replace(
        outcome, result=replace(outcome.result, records=records, records_captured=len(records))
    )


def test_write_measured_brief_refuses_a_candidate_with_no_field_inventory(
    tmp_path: Path,
) -> None:
    # A catalog-channel candidate: the prompt fell back to the canonical list, the reader
    # answered, measure succeeded, and every locator joined onto no FieldSpec.
    with pytest.raises(inv.NothingToMeasure, match="no field inventory at all"):
        inv.write_measured_brief(
            tmp_path,
            _candidate(),
            _outcome(),
            dict(_MEASURABLE_LOCATORS),
            now="2026-08-31T14:02:11Z",
        )


def test_write_measured_brief_refuses_an_inventory_that_marks_everything_absent(
    tmp_path: Path,
) -> None:
    candidate = _candidate(race=FieldSpec(present=False, location=Location.ABSENT))
    with pytest.raises(inv.NothingToMeasure, match="absent or not present"):
        inv.write_measured_brief(
            tmp_path,
            candidate,
            _outcome(),
            dict(_MEASURABLE_LOCATORS),
            now="2026-08-31T14:02:11Z",
        )


def test_write_measured_brief_refuses_a_vocabulary_desync(tmp_path: Path) -> None:
    candidate = _candidate(age=FieldSpec(present=True, location=Location.STRUCTURED))
    locators = {"victim_age": Locator("victim_age", LocatorKind.CSS, "strong", "detail")}
    with pytest.raises(inv.NothingToMeasure, match="different vocabularies"):
        inv.write_measured_brief(
            tmp_path, candidate, _outcome(), locators, now="2026-08-31T14:02:11Z"
        )


def test_write_measured_brief_refuses_a_floors_block_that_is_entirely_vacuous(
    tmp_path: Path,
) -> None:
    candidate = _candidate(county=FieldSpec(present=True, location=Location.NARRATIVE))
    with pytest.raises(inv.NothingToMeasure, match="every derived floor is 0.0"):
        inv.write_measured_brief(
            tmp_path,
            candidate,
            _thin_outcome(_thin_corpus()),
            dict(_THIN_LOCATORS),
            now="2026-08-31T14:02:11Z",
        )


def test_write_measured_brief_accepts_a_block_with_one_floor_that_can_fail(
    tmp_path: Path,
) -> None:
    # The vacuous floor is recorded rather than refused when something else can fail.
    candidate = _candidate(
        county=FieldSpec(present=True, location=Location.NARRATIVE),
        age=FieldSpec(present=True, location=Location.STRUCTURED),
    )
    records = _thin_corpus() + [
        CapturedRecord(key="d0", payload="<p><strong>AGE:</strong> 34</p>", page="detail")
    ]
    locators = dict(_THIN_LOCATORS)
    locators["age"] = Locator("age", LocatorKind.CSS, "strong", "detail")
    path, _ = inv.write_measured_brief(
        tmp_path, candidate, _thin_outcome(records), locators, now="2026-08-31T14:02:11Z"
    )
    assert _brief(path)["vacuous_floors"] == ["county"]
    assert _brief(path)["floors"]["victim_age"] == 0.95


def test_write_measured_brief_records_the_suspected_page_mismatch(tmp_path: Path) -> None:
    candidate = _candidate(
        narrative=FieldSpec(present=True, location=Location.NARRATIVE, page=Page.LIST),
        age=FieldSpec(present=True, location=Location.STRUCTURED, page=Page.DETAIL),
    )
    locators = {
        "narrative": Locator("narrative", LocatorKind.LABEL, "NARRATIVE:", "list"),
        "age": Locator("age", LocatorKind.CSS, "p", "detail"),
    }
    path, _ = inv.write_measured_brief(
        tmp_path,
        candidate,
        _thin_outcome(_mispaged_corpus()),
        locators,
        now="2026-08-31T14:02:11Z",
    )
    assert _brief(path)["suspected_page_mismatch"] == ["narrative"]


# --- the margin's value, not just its direction ---


def _bracketing_corpus(list_hits: int, detail_hits: int) -> list[CapturedRecord]:
    """A hundred records on each page, of which the named counts carry the field."""
    records = [
        CapturedRecord(
            key=f"l{i}",
            payload="<p>COUNTY: Tulsa</p>" if i < list_hits else "<p>nothing</p>",
            page="list",
        )
        for i in range(100)
    ]
    records += [
        CapturedRecord(
            key=f"d{i}",
            payload="<p>COUNTY: Tulsa</p>" if i < detail_hits else "<p>nothing</p>",
            page="detail",
        )
        for i in range(100)
    ]
    return records


_MARGIN_LOCATORS = {"county": Locator("county", LocatorKind.LABEL, "COUNTY:", "list")}


def test_a_rival_inside_the_margin_is_not_reported() -> None:
    # 0.50 on the locator's page against 0.70 elsewhere: better by 0.20, the smallest
    # difference MISPAGED_MARGIN is meant to tolerate. With the test below this pins the
    # constant to [0.20, 0.35) -- tight enough that 0.11 or 0.9 goes red, wide enough that
    # ordinary re-tuning (0.25 -> 0.30) still passes. The two direction tests it replaced
    # left every value from 0.11 to 0.96 passing; a first attempt at this pair pinned
    # [0.24, 0.26), which caught the same defects and also refused legitimate tuning.
    entry = inv.measure(_bracketing_corpus(50, 70), dict(_MARGIN_LOCATORS))["county"]
    assert entry.coverage == pytest.approx(0.50)
    assert entry.better_on_page is None


def test_a_rival_outside_the_margin_is_reported() -> None:
    # Better by 0.35: past any value the margin should be tuned to.
    entry = inv.measure(_bracketing_corpus(50, 85), dict(_MARGIN_LOCATORS))["county"]
    assert entry.coverage == pytest.approx(0.50)
    assert entry.better_on_page == "detail"
    assert entry.better_page_coverage == pytest.approx(0.85)


def test_the_mispaged_margin_is_a_non_negative_fraction() -> None:
    # _better_page skips the locator's own page for cost rather than for correctness: a
    # page scores identically to itself, so the margin excludes it anyway. That
    # redundancy holds only while the margin is non-negative, and an unfalsifiable
    # assumption is the thing this module removed elsewhere, so it is asserted here.
    assert 0.0 <= inv.MISPAGED_MARGIN < 1.0


# --- the route that had no test and the least useful message ---


def test_write_measured_brief_refuses_when_every_locator_is_for_an_absent_field(
    tmp_path: Path,
) -> None:
    # The fifth route. The inventory names a present field, so the all-absent route does
    # not fire; the locator IS in the inventory, so the vocabulary route does not either.
    # It is precisely diagnosable: the reader located what the classifier said the source
    # does not publish.
    candidate = _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED),
        race=FieldSpec(present=False, location=Location.ABSENT),
    )
    locators = {"race": Locator("race", LocatorKind.CSS, "strong", "detail")}
    with pytest.raises(inv.NothingToMeasure, match="the classifier said this source does"):
        inv.write_measured_brief(
            tmp_path, candidate, _outcome(), locators, now="2026-08-31T14:02:11Z"
        )


def test_a_locator_on_a_field_marked_not_present_is_diagnosed() -> None:
    # present=False with a non-ABSENT location: the not-present half of the eligibility
    # rule, which the ABSENT half alone would miss.
    candidate = _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED),
        race=FieldSpec(present=False, location=Location.STRUCTURED),
    )
    locators = {"race": Locator("race", LocatorKind.CSS, "strong", "detail")}
    reason = inv.measure_capture(candidate, RECORDS, locators).floors_assert_nothing
    assert reason is not None
    assert "the classifier said this source does" in reason


def test_a_locator_on_a_present_field_recorded_absent_is_diagnosed() -> None:
    # present=True with location ABSENT: the other half, which not-present alone misses.
    candidate = _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED),
        race=FieldSpec(present=True, location=Location.ABSENT),
    )
    locators = {"race": Locator("race", LocatorKind.CSS, "strong", "detail")}
    reason = inv.measure_capture(candidate, RECORDS, locators).floors_assert_nothing
    assert reason is not None
    assert "the classifier said this source does" in reason


def test_the_absent_field_route_names_the_offending_field(tmp_path: Path) -> None:
    candidate = _candidate(
        age=FieldSpec(present=True, location=Location.STRUCTURED),
        race=FieldSpec(present=False, location=Location.ABSENT),
    )
    locators = {"race": Locator("race", LocatorKind.CSS, "strong", "detail")}
    measurement = inv.measure_capture(candidate, RECORDS, locators)
    reason = measurement.floors_assert_nothing
    assert reason is not None
    # Named in the DIAGNOSIS, not merely in the preamble listing what was measured: a
    # mutant emptying the ineligible list survived an "in reason" assertion, because the
    # preamble names the field either way.
    assert "race name field(s) the inventory marks absent" in reason


def test_a_measurement_whose_floors_can_fail_reports_no_reason() -> None:
    measurement = inv.measure_capture(
        _measurable_candidate(), RECORDS, dict(_MEASURABLE_LOCATORS)
    )
    assert measurement.floors_assert_nothing is None


# --- the refusal speaks the operator's vocabulary ---


def test_the_vacuous_refusal_names_inventory_fields_not_adapter_fields() -> None:
    # locators.json and the field inventory both say victim_name; case_name appears in
    # neither, so an operator sent looking for it has nowhere to look.
    candidate = _candidate(victim_name=FieldSpec(present=True, location=Location.NARRATIVE))
    records = [CapturedRecord(key="r0", payload="<p>NAME: Ann Example</p>", page="list")]
    records += [
        CapturedRecord(key=f"r{i}", payload="<p>nothing</p>", page="list") for i in range(1, 10)
    ]
    locators = {"victim_name": Locator("victim_name", LocatorKind.LABEL, "NAME:", "list")}
    reason = inv.measure_capture(candidate, records, locators).floors_assert_nothing
    assert reason is not None
    assert "victim_name" in reason
    assert "case_name" not in reason


def test_the_vacuous_refusal_does_not_claim_the_coverage_was_below_the_tolerance() -> None:
    # At coverage 0.1001 the floor is 0.0 only because 9.99e-5 truncates at four decimal
    # places -- the coverage is ABOVE the tolerance, so the old wording was untrue.
    records = [
        CapturedRecord(
            key=f"r{i}",
            payload="<p>COUNTY: Tulsa</p>" if i < 1001 else "<p>nothing</p>",
            page="list",
        )
        for i in range(10000)
    ]
    candidate = _candidate(county=FieldSpec(present=True, location=Location.NARRATIVE))
    measurement = inv.measure_capture(candidate, records, dict(_THIN_LOCATORS))
    assert measurement.coverage["county"].coverage == pytest.approx(0.1001)
    assert measurement.floors == {"county": 0.0}
    reason = measurement.floors_assert_nothing
    assert reason is not None
    assert "at or below" not in reason
    assert "truncates to zero" in reason
