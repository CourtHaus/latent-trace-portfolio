"""The reader pass: prompt contract, tool grant, and the strictness of the loaders.

The loaders are where most of these tests live, because everything downstream is
built on their output and a lenient reader would hand Task 10 a field with no floor
and Task 11 a test that asserts nothing. Each refusal below names the branch it
pins, so a later reader can tell a coverage test from a feature test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from casesignal.drafter import reader
from casesignal.drafter.client import ALLOWED_TOOLS, FakeDrafterClient
from casesignal.scout.models import (
    Candidate,
    Channel,
    FieldSpec,
    Level,
    Location,
    LocatorKind,
    Page,
)


def _candidate(**kwargs: object) -> Candidate:
    return Candidate(
        id="ok__osbi",
        level=Level.STATE,
        state="OK",
        index_url="https://oklahoma.gov/x",
        channel=Channel.WEB,
        **kwargs,  # type: ignore[arg-type]
    )


FIXTURES = ["listing_1.html"]


@pytest.fixture(autouse=True)
def captured_fixture(tmp_path: Path) -> None:
    (tmp_path / "listing_1.html").write_text("<li class='case'>COUNTY: Tulsa</li>")


# --- prompt ---


def test_prompt_names_the_fixtures_and_forbids_race_inference() -> None:
    prompt = reader.build_reader_prompt(_candidate(), ["fx/listing_1.html"], Path("out"))
    assert "fx/listing_1.html" in prompt
    assert "never infer" in prompt.lower()
    assert "locators.json" in prompt and "expectations.json" in prompt


def test_prompt_carries_the_standing_race_rule_verbatim() -> None:
    """The platform rule, not a preference: the wording matches scout/classify.py."""
    prompt = reader.build_reader_prompt(_candidate(), ["fx/listing_1.html"], Path("out"))
    assert "Never infer race; only record whether the SOURCE provides it as a field." in prompt


def test_prompt_names_the_out_dir_for_both_files() -> None:
    prompt = reader.build_reader_prompt(_candidate(), FIXTURES, Path("data/drafts/ok"))
    assert "data/drafts/ok/locators.json" in prompt
    assert "data/drafts/ok/expectations.json" in prompt


def test_prompt_asks_for_the_three_sampled_records() -> None:
    prompt = reader.build_reader_prompt(_candidate(), FIXTURES, Path("out"))
    assert "FIRST record" in prompt
    assert "LAST record" in prompt
    assert "DEGENERATE" in prompt


def test_prompt_states_the_capture_record_key_form() -> None:
    """Task 11 cannot render a test that finds the record unless the key matches."""
    prompt = reader.build_reader_prompt(_candidate(), FIXTURES, Path("out"))
    assert "listing_1.html#0" in prompt
    assert "LISTING" in prompt


def test_prompt_embeds_both_schemas() -> None:
    prompt = reader.build_reader_prompt(_candidate(), FIXTURES, Path("out"))
    assert json.dumps(reader.LOCATORS_SCHEMA, indent=2) in prompt
    assert json.dumps(reader.EXPECTATIONS_SCHEMA, indent=2) in prompt


def test_prompt_field_list_comes_from_the_candidate_inventory() -> None:
    """Locator keys must match inventory keys or Task 10 measures nothing."""
    candidate = _candidate(
        fields={
            "victim_name": FieldSpec(present=True, location=Location.STRUCTURED, page=Page.LIST),
            "narrative": FieldSpec(present=True, location=Location.NARRATIVE, page=Page.DETAIL),
        }
    )
    prompt = reader.build_reader_prompt(candidate, FIXTURES, Path("out"))
    assert "- victim_name (recorded as structured, on the list)" in prompt
    assert "- narrative (recorded as narrative, on the detail)" in prompt
    # The canonical fallback list is NOT in play when an inventory exists.
    assert "- case_number" not in prompt


def test_prompt_omits_fields_the_inventory_marks_not_present() -> None:
    """A locator for an absent field is a hard error in the inventory pass."""
    candidate = _candidate(
        fields={
            "victim_name": FieldSpec(present=True, location=Location.STRUCTURED, page=Page.LIST),
            "race": FieldSpec(present=False, location=Location.ABSENT),
        }
    )
    prompt = reader.build_reader_prompt(candidate, FIXTURES, Path("out"))
    assert "- victim_name" in prompt
    assert "- race" not in prompt


def test_prompt_names_a_field_with_no_recorded_page() -> None:
    candidate = _candidate(
        fields={"county": FieldSpec(present=True, location=Location.NARRATIVE, page=None)}
    )
    prompt = reader.build_reader_prompt(candidate, FIXTURES, Path("out"))
    assert "- county (recorded as narrative, on the unknown page)" in prompt


def test_prompt_falls_back_to_the_canonical_fields_without_an_inventory() -> None:
    prompt = reader.build_reader_prompt(_candidate(), FIXTURES, Path("out"))
    for name in reader.CANONICAL_FIELDS:
        assert f"  - {name}" in prompt


def test_prompt_refuses_a_round_with_no_fixtures() -> None:
    """A prompt naming no fixtures asks for values transcribed from nowhere."""
    with pytest.raises(reader.InvalidReaderOutput, match="no fixtures"):
        reader.build_reader_prompt(_candidate(), [], Path("out"))


# --- schemas ---


def test_locators_schema_enumerates_exactly_the_locator_kinds() -> None:
    """The schema the agent is shown and the set the loader accepts must not drift."""
    kinds = reader.LOCATORS_SCHEMA["additionalProperties"]["properties"]["kind"]["enum"]
    assert kinds == sorted(kind.value for kind in LocatorKind)


def test_locators_schema_enumerates_exactly_the_pages() -> None:
    pages = reader.LOCATORS_SCHEMA["additionalProperties"]["properties"]["page"]["enum"]
    assert sorted(pages) == sorted(page.value for page in Page)


def test_expectations_schema_requires_both_halves_of_a_record() -> None:
    assert reader.EXPECTATIONS_SCHEMA["items"]["required"] == ["record_key", "values"]


# --- tool grant ---


def test_reader_tools_are_a_narrowing_of_the_client_allowlist() -> None:
    assert set(reader.READER_TOOLS) < set(ALLOWED_TOOLS)


def test_reader_cannot_edit_or_execute() -> None:
    """It creates two files that do not exist; Edit would let it rewrite the repo."""
    assert "Edit" not in reader.READER_TOOLS
    assert "Bash" not in reader.READER_TOOLS
    assert "Write" in reader.READER_TOOLS


def test_reader_tool_grant_is_exactly_read_grep_write() -> None:
    """Glob's absence is an argued decision, so it is pinned rather than described.

    Withholding it is what makes "read ONLY these fixtures" partly enforced instead of
    wholly instructed: the prompt names every path, so the reader has nothing to
    discover. A subset assertion alone would let Glob back in unnoticed.
    """
    assert reader.READER_TOOLS == ("Read", "Grep", "Write")


# --- load_locators ---


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_locators_parses_each_kind(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "locators.json",
        {
            "victim_age": {"kind": "css", "value": "strong:contains('AGE:')", "page": "detail"},
            "county": {"kind": "label", "value": "COUNTY:", "page": "detail"},
            "case_number": {"kind": "json_path", "value": "attributes.CASE_NO", "page": "list"},
        },
    )
    loaded = reader.load_locators(path)
    assert loaded["victim_age"].kind is LocatorKind.CSS
    assert loaded["county"].kind is LocatorKind.LABEL
    assert loaded["case_number"].value == "attributes.CASE_NO"
    assert loaded["case_number"].page == "list"
    assert loaded["county"].field == "county"


def test_load_locators_rejects_a_file_that_names_no_fields(tmp_path: Path) -> None:
    """An empty file measures nothing, so the draft would verify PASS unverified."""
    path = _write(tmp_path / "locators.json", {})
    with pytest.raises(reader.InvalidReaderOutput, match="names no fields"):
        reader.load_locators(path)


def test_load_locators_rejects_an_unknown_kind(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "locators.json",
        {"victim_age": {"kind": "xpath", "value": "//x", "page": "detail"}},
    )
    with pytest.raises(reader.InvalidReaderOutput, match="xpath"):
        reader.load_locators(path)


def test_load_locators_rejects_an_unknown_page(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "locators.json", {"county": {"kind": "label", "value": "C:", "page": "footer"}}
    )
    with pytest.raises(reader.InvalidReaderOutput, match="footer"):
        reader.load_locators(path)


def test_load_locators_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(reader.InvalidReaderOutput, match="locators.json"):
        reader.load_locators(tmp_path / "locators.json")


def test_load_locators_rejects_unparseable_json(tmp_path: Path) -> None:
    path = tmp_path / "locators.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(reader.InvalidReaderOutput, match="not valid JSON"):
        reader.load_locators(path)


def test_load_locators_rejects_a_top_level_array(tmp_path: Path) -> None:
    path = _write(tmp_path / "locators.json", [{"kind": "css", "value": "b", "page": "list"}])
    with pytest.raises(reader.InvalidReaderOutput, match="must be a JSON object"):
        reader.load_locators(path)


def test_load_locators_rejects_a_blank_field_name(tmp_path: Path) -> None:
    path = _write(tmp_path / "locators.json", {"  ": {"kind": "css", "value": "b", "page": "list"}})
    with pytest.raises(reader.InvalidReaderOutput, match="must not be blank"):
        reader.load_locators(path)


def test_load_locators_rejects_a_locator_that_is_not_an_object(tmp_path: Path) -> None:
    path = _write(tmp_path / "locators.json", {"county": "COUNTY:"})
    with pytest.raises(reader.InvalidReaderOutput, match="'COUNTY:'"):
        reader.load_locators(path)


def test_load_locators_rejects_a_missing_kind(tmp_path: Path) -> None:
    path = _write(tmp_path / "locators.json", {"county": {"value": "COUNTY:", "page": "list"}})
    with pytest.raises(reader.InvalidReaderOutput, match="'kind' must be a string, got None"):
        reader.load_locators(path)


def test_load_locators_rejects_a_null_value(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "locators.json", {"county": {"kind": "label", "value": None, "page": "list"}}
    )
    with pytest.raises(reader.InvalidReaderOutput, match="'value' must be a string"):
        reader.load_locators(path)


def test_load_locators_rejects_an_empty_value(tmp_path: Path) -> None:
    """An empty selector matches everything or nothing; neither is a locator."""
    path = _write(
        tmp_path / "locators.json", {"county": {"kind": "label", "value": "   ", "page": "list"}}
    )
    with pytest.raises(reader.InvalidReaderOutput, match="'value' must not be blank"):
        reader.load_locators(path)


def test_load_locators_rejects_a_missing_page(tmp_path: Path) -> None:
    path = _write(tmp_path / "locators.json", {"county": {"kind": "label", "value": "C:"}})
    with pytest.raises(reader.InvalidReaderOutput, match="'page' must be a string, got None"):
        reader.load_locators(path)


# --- load_expectations ---


def test_load_expectations_requires_a_record_key_and_values(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "expectations.json",
        [{"record_key": "listing_1.html#0", "values": {"case_name": "Ann Example"}}],
    )
    loaded = reader.load_expectations(path)
    assert loaded[0].record_key == "listing_1.html#0"
    assert loaded[0].values["case_name"] == "Ann Example"


def test_load_expectations_rejects_a_file_that_holds_no_records(tmp_path: Path) -> None:
    """With no golden values, nothing separates a working parser from a consistent one."""
    path = _write(tmp_path / "expectations.json", [])
    with pytest.raises(reader.InvalidReaderOutput, match="no records"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_record_without_values(tmp_path: Path) -> None:
    path = _write(tmp_path / "expectations.json", [{"record_key": "x"}])
    with pytest.raises(reader.InvalidReaderOutput, match="values"):
        reader.load_expectations(path)


def test_load_expectations_rejects_empty_values(tmp_path: Path) -> None:
    """A record with no expectations renders a test that always passes."""
    path = _write(tmp_path / "expectations.json", [{"record_key": "x", "values": {}}])
    with pytest.raises(reader.InvalidReaderOutput, match="asserts nothing"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(reader.InvalidReaderOutput, match="expectations.json"):
        reader.load_expectations(tmp_path / "expectations.json")


def test_load_expectations_rejects_unparseable_json(tmp_path: Path) -> None:
    path = tmp_path / "expectations.json"
    path.write_text("[", encoding="utf-8")
    with pytest.raises(reader.InvalidReaderOutput, match="not valid JSON"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_top_level_object(tmp_path: Path) -> None:
    path = _write(tmp_path / "expectations.json", {"record_key": "x", "values": {"a": "b"}})
    with pytest.raises(reader.InvalidReaderOutput, match="must be a JSON array"):
        reader.load_expectations(path)


def test_load_expectations_rejects_an_entry_that_is_not_an_object(tmp_path: Path) -> None:
    path = _write(tmp_path / "expectations.json", ["listing_1.html#0"])
    with pytest.raises(reader.InvalidReaderOutput, match="expectation 0 must be an object"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_missing_record_key(tmp_path: Path) -> None:
    path = _write(tmp_path / "expectations.json", [{"values": {"a": "b"}}])
    with pytest.raises(reader.InvalidReaderOutput, match="'record_key' must be a string"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_blank_record_key(tmp_path: Path) -> None:
    path = _write(tmp_path / "expectations.json", [{"record_key": " ", "values": {"a": "b"}}])
    with pytest.raises(reader.InvalidReaderOutput, match="'record_key' must not be blank"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_duplicate_record_key(tmp_path: Path) -> None:
    """Two entries for one record render two tests with the same generated name."""
    path = _write(
        tmp_path / "expectations.json",
        [
            {"record_key": "listing_1.html#0", "values": {"a": "b"}},
            {"record_key": "listing_1.html#0", "values": {"a": "c"}},
        ],
    )
    with pytest.raises(reader.InvalidReaderOutput, match="repeats record_key"):
        reader.load_expectations(path)


def test_load_expectations_rejects_values_that_are_not_an_object(tmp_path: Path) -> None:
    path = _write(tmp_path / "expectations.json", [{"record_key": "x", "values": "Ann Example"}])
    with pytest.raises(reader.InvalidReaderOutput, match="must carry 'values' as an object"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_non_string_expected_value(tmp_path: Path) -> None:
    """A bare 34 and the source's "34" are not the same assertion."""
    path = _write(tmp_path / "expectations.json", [{"record_key": "x", "values": {"age": 34}}])
    with pytest.raises(reader.InvalidReaderOutput, match="which is a int"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_blank_expected_value(tmp_path: Path) -> None:
    """`assert extracted == ""` is passed by a parser that never found the field."""
    path = _write(tmp_path / "expectations.json", [{"record_key": "x", "values": {"county": ""}}])
    with pytest.raises(reader.InvalidReaderOutput, match="expects 'county' to be blank"):
        reader.load_expectations(path)


def test_load_expectations_rejects_a_blank_field_name(tmp_path: Path) -> None:
    path = _write(tmp_path / "expectations.json", [{"record_key": "x", "values": {" ": "b"}}])
    with pytest.raises(reader.InvalidReaderOutput, match="blank field name"):
        reader.load_expectations(path)


def test_load_expectations_keeps_every_record_in_order(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "expectations.json",
        [
            {"record_key": "listing_1.html#0", "values": {"a": "1"}},
            {"record_key": "listing_2.html#7", "values": {"a": "2"}},
            {"record_key": "listing_1.html#3", "values": {"a": "3"}},
        ],
    )
    loaded = reader.load_expectations(path)
    assert [r.record_key for r in loaded] == [
        "listing_1.html#0",
        "listing_2.html#7",
        "listing_1.html#3",
    ]


def test_load_locators_rejects_a_repeated_object_key(tmp_path: Path) -> None:
    """JSON resolves a repeated key last-wins; one locator would vanish silently."""
    path = tmp_path / "locators.json"
    path.write_text(
        '{"county": {"kind": "label", "value": "A:", "page": "list"},'
        ' "county": {"kind": "label", "value": "B:", "page": "list"}}',
        encoding="utf-8",
    )
    with pytest.raises(reader.InvalidReaderOutput, match="repeats the object key 'county'"):
        reader.load_locators(path)


def test_load_expectations_rejects_a_repeated_key_inside_values(tmp_path: Path) -> None:
    path = tmp_path / "expectations.json"
    path.write_text('[{"record_key": "x", "values": {"age": "34", "age": "51"}}]', encoding="utf-8")
    with pytest.raises(reader.InvalidReaderOutput, match="repeats the object key 'age'"):
        reader.load_expectations(path)


# --- run_reader ---


def _emit(cwd: Path) -> None:
    _write(
        cwd / "locators.json",
        {"county": {"kind": "label", "value": "COUNTY:", "page": "detail"}},
    )
    _write(
        cwd / "expectations.json",
        [{"record_key": "listing_1.html#0", "values": {"county": "Tulsa"}}],
    )


def test_run_reader_returns_what_the_round_wrote(tmp_path: Path) -> None:
    client = FakeDrafterClient([_emit])
    locators, expectations = reader.run_reader(
        _candidate(), client, fixture_paths=FIXTURES, out_dir=tmp_path, cwd=tmp_path
    )
    assert locators["county"].value == "COUNTY:"
    assert expectations[0].values["county"] == "Tulsa"


def test_run_reader_grants_only_the_reader_tools_and_a_spend_ceiling(tmp_path: Path) -> None:
    client = FakeDrafterClient([_emit])
    reader.run_reader(_candidate(), client, fixture_paths=FIXTURES, out_dir=tmp_path, cwd=tmp_path)
    call = client.calls[0]
    assert call["allowed_tools"] == reader.READER_TOOLS
    assert call["max_budget_usd"] == reader.DEFAULT_READER_BUDGET_USD
    assert call["timeout_s"] == reader.DEFAULT_READER_TIMEOUT_S
    assert client.prompts[0].startswith("You are reading captured fixtures")


def test_run_reader_refuses_a_round_that_wrote_nothing(tmp_path: Path) -> None:
    client = FakeDrafterClient([lambda cwd: None])
    with pytest.raises(reader.InvalidReaderOutput, match="locators.json"):
        reader.run_reader(
            _candidate(), client, fixture_paths=FIXTURES, out_dir=tmp_path, cwd=tmp_path
        )


def test_run_reader_refuses_before_buying_a_round_with_no_fixtures(tmp_path: Path) -> None:
    """The refusal has to land before client.run, or the round is billed anyway."""
    client = FakeDrafterClient([_emit])
    with pytest.raises(reader.InvalidReaderOutput, match="no fixtures"):
        reader.run_reader(_candidate(), client, fixture_paths=[], out_dir=tmp_path, cwd=tmp_path)
    assert client.calls == []


def test_run_reader_refuses_an_out_dir_outside_the_working_directory(tmp_path: Path) -> None:
    """--restricted confines the file tools to cwd, so the round could not write there."""
    cwd = tmp_path / "worktree"
    cwd.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    client = FakeDrafterClient([_emit])
    with pytest.raises(reader.InvalidReaderOutput, match="outside the reader's working directory"):
        reader.run_reader(_candidate(), client, fixture_paths=FIXTURES, out_dir=outside, cwd=cwd)
    assert client.calls == []


def test_run_reader_accepts_an_out_dir_below_the_working_directory(tmp_path: Path) -> None:
    out = tmp_path / "draft" / "ok"
    out.mkdir(parents=True)
    locators, _ = reader.run_reader(
        _candidate(),
        FakeDrafterClient([_emit]),
        fixture_paths=FIXTURES,
        out_dir=out,
        cwd=tmp_path,
    )
    assert "county" in locators


def test_run_reader_refuses_a_locator_the_inventory_does_not_name(tmp_path: Path) -> None:
    """It measures fine and then joins onto nothing: no floor, and no other signal."""
    candidate = _candidate(
        fields={"age": FieldSpec(present=True, location=Location.STRUCTURED, page=Page.DETAIL)}
    )

    def emit(cwd: Path) -> None:
        _write(
            cwd / "locators.json",
            {"victim_age": {"kind": "label", "value": "AGE:", "page": "detail"}},
        )
        _write(
            cwd / "expectations.json",
            [{"record_key": "listing_1.html#0", "values": {"age": "34"}}],
        )

    with pytest.raises(reader.InvalidReaderOutput, match="victim_age"):
        reader.run_reader(
            candidate,
            FakeDrafterClient([emit]),
            fixture_paths=FIXTURES,
            out_dir=tmp_path,
            cwd=tmp_path,
        )


def test_run_reader_refuses_a_locator_for_a_field_the_inventory_marks_absent(
    tmp_path: Path,
) -> None:
    """The join would not break, but a race locator that matches anything at all
    manufactures coverage for a field the source does not publish, and race is where
    this platform's standing rule makes that least acceptable."""
    candidate = _candidate(
        fields={
            "victim_name": FieldSpec(present=True, location=Location.STRUCTURED, page=Page.LIST),
            "race": FieldSpec(present=False, location=Location.ABSENT),
        }
    )

    def emit(cwd: Path) -> None:
        _write(
            cwd / "locators.json",
            {
                "victim_name": {"kind": "css", "value": "h3", "page": "list"},
                "race": {"kind": "css", "value": "td", "page": "list"},
            },
        )
        _write(
            cwd / "expectations.json",
            [{"record_key": "listing_1.html#0", "values": {"victim_name": "Ann Example"}}],
        )

    with pytest.raises(reader.InvalidReaderOutput, match="did not ask for: race"):
        reader.run_reader(
            candidate,
            FakeDrafterClient([emit]),
            fixture_paths=FIXTURES,
            out_dir=tmp_path,
            cwd=tmp_path,
        )


def test_run_reader_skips_the_check_when_the_prompt_fell_back_to_canonical_fields(
    tmp_path: Path,
) -> None:
    """An inventory marking everything absent renders the CANONICAL_FIELDS prompt, so
    refusing canonical-vocabulary locators back would contradict what was asked."""
    candidate = _candidate(fields={"race": FieldSpec(present=False, location=Location.ABSENT)})
    assert "  - county" in reader.build_reader_prompt(candidate, FIXTURES, Path("out"))
    locators, _ = reader.run_reader(
        candidate,
        FakeDrafterClient([_emit]),
        fixture_paths=FIXTURES,
        out_dir=tmp_path,
        cwd=tmp_path,
    )
    assert "county" in locators


def test_requested_fields_is_what_the_prompt_asks_for(tmp_path: Path) -> None:
    candidate = _candidate(
        fields={
            "victim_name": FieldSpec(present=True, location=Location.STRUCTURED, page=Page.LIST),
            "race": FieldSpec(present=False, location=Location.ABSENT),
        }
    )
    assert sorted(reader.requested_fields(candidate)) == ["victim_name"]


def test_run_reader_allows_any_locator_when_the_candidate_has_no_inventory(
    tmp_path: Path,
) -> None:
    """A catalog-channel candidate arrives without fields; nothing to check against."""
    locators, _ = reader.run_reader(
        _candidate(),
        FakeDrafterClient([_emit]),
        fixture_paths=FIXTURES,
        out_dir=tmp_path,
        cwd=tmp_path,
    )
    assert "county" in locators


def test_run_reader_refuses_a_failed_round(tmp_path: Path) -> None:
    class Failing:
        def run(self, prompt: str, **kwargs: object) -> object:
            from casesignal.drafter.client import DrafterResult

            return DrafterResult(ok=False, text="timed out after 600s", raw={})

    with pytest.raises(reader.InvalidReaderOutput, match="timed out after 600s"):
        reader.run_reader(
            _candidate(),
            Failing(),  # type: ignore[arg-type]
            fixture_paths=FIXTURES,
            out_dir=tmp_path,
            cwd=tmp_path,
        )


@pytest.mark.parametrize("unsafe", ["absolute", "parent"])
def test_reader_refuses_paths_that_escape_the_copy_directory(tmp_path: Path, unsafe: str) -> None:
    name = (
        str(tmp_path / "listing_1.html")
        if unsafe == "absolute"
        else "../" + tmp_path.name + "/listing_1.html"
    )
    client = FakeDrafterClient([])
    with pytest.raises(reader.InvalidReaderOutput, match="unsafe reader fixture path"):
        reader.run_reader(
            _candidate(), client, fixture_paths=[name], out_dir=tmp_path, cwd=tmp_path
        )
    assert client.calls == []
