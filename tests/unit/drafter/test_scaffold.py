"""The generator's tests: what it refuses, what it renders, and what it edits.

The refusal tests carry the weight here. A generator that renders a plausible
adapter package from an unmeasured brief produces a branch that compiles, imports,
and reports PASS over floors nobody measured -- and every later pass in the chain
reads that as a drafted source. So the three routes to a meaningless floors block
are asserted individually, and so is the mixture the inventory pass cannot see.
"""

from __future__ import annotations

import ast
import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from casesignal.drafter import scaffold
from casesignal.drafter.reader import ExpectedRecord
from casesignal.drafter.scaffold import Brief, ScaffoldRefusal, UnmeasuredBrief

REPO_ROOT = Path(__file__).resolve().parents[3]


def make_brief(**overrides: Any) -> Brief:
    """A measured census brief, the ordinary case every other test perturbs."""
    defaults: dict[str, Any] = {
        "adapter_name": "cold_case_ok_osbi",
        "source_key": "cold_case_ok_osbi_2026_08_31",
        "state": "OK",
        "floors": {"victim_age": 0.95},
        "records_captured": 307,
        "records_total": 307,
        "listing_record_count": 307,
        "inventory_measured": True,
        "index_url": "https://oklahoma.gov/osbi/cold-cases.html",
        "captured_at": "2026-08-31T10:00:00Z",
        "session_id": "sess-1",
        "agency": "Oklahoma State Bureau of Investigation",
        "shape": "html",
        "transport": "httpx",
        "channel": "web",
        "listing_paths": ("listing/range_a-b.html",),
        "detail_paths": (),
        "fixtures_root": "/tmp/draft/fixtures",
        "source_id_strategy": "synthesized",
        "locators": {"victim_age": {"kind": "label", "value": "AGE:", "page": "list"}},
        "coverage": {"victim_age": {"matched": 300, "total": 307, "coverage": 0.9772}},
    }
    defaults.update(overrides)
    return Brief(**defaults)


def _with_run_pipeline(repo_root: Path) -> Path:
    """A fake repo root holding the one file register_adapter needs to anchor on."""
    runners = repo_root / "src/casesignal/etl/runners"
    runners.mkdir(parents=True, exist_ok=True)
    (runners / "run_pipeline.py").write_text(
        "from casesignal.etl.adapters.cold_case_va.adapter import ColdCaseVAAdapter\n"
        "\n"
        "def build_adapter_registry():\n"
        "    registry.register(ColdCaseVAAdapter)\n"
        "    return registry\n"
    )
    return repo_root


def _exec_generated(rendered: str) -> dict[str, Any]:
    """Run a generated test module's body without its adapter import.

    The adapter it imports does not exist here; everything asserted about the
    module's own constants and guards is above that line.
    """
    body = "\n".join(
        line
        for line in rendered.splitlines()
        if not line.startswith("from casesignal.etl.adapters")
    )
    namespace: dict[str, Any] = {
        "__file__": "/nowhere/tests/unit/etl/adapters/generated.py",
        "__name__": "generated",
    }
    exec(compile(body, "<generated>", "exec"), namespace)  # noqa: S102
    return namespace


# --- obligation 1: refuse an unmeasured brief, by all three routes ---


def test_a_brief_that_was_never_measured_is_refused() -> None:
    with pytest.raises(UnmeasuredBrief, match="inventory_measured is false"):
        make_brief(inventory_measured=False)


def test_the_measured_flag_alone_does_not_earn_a_draft() -> None:
    """`inventory_measured: true` over an empty floors block is the reviewed hole."""
    with pytest.raises(UnmeasuredBrief, match="empty floors block"):
        make_brief(floors={})


def test_floors_that_cannot_fail_are_refused() -> None:
    with pytest.raises(UnmeasuredBrief, match="every derived floor is 0.0"):
        make_brief(floors={"victim_age": 0.0, "county": 0.0})


def test_a_measured_brief_with_one_failing_floor_is_accepted() -> None:
    assert make_brief(floors={"victim_age": 0.0, "county": 0.9}).failing_floors == {
        "county": 0.9
    }


def test_a_field_name_that_is_not_an_identifier_is_refused() -> None:
    """Floor names reach generated SQL and generated identifiers unescaped."""
    with pytest.raises(ScaffoldRefusal, match="not a lowercase identifier"):
        make_brief(floors={"victim_age); DROP TABLE cases; --": 0.9})


def test_from_mapping_keeps_every_refusal() -> None:
    data = {
        "adapter_name": "cold_case_ok_osbi",
        "source_key": "k",
        "state": "OK",
        "floors": {"victim_age": 0.95},
        "records_captured": 3,
        "records_total": 3,
        "listing_record_count": 3,
        "inventory_measured": False,
        "unknown_key_from_a_later_brief": 1,
    }
    with pytest.raises(UnmeasuredBrief):
        Brief.from_mapping(data)
    measured = Brief.from_mapping({**data, "inventory_measured": True})
    assert measured.adapter_name == "cold_case_ok_osbi"


# --- obligation 5: idempotent shared-file edits, keyed on adapter_name ---


def test_append_source_yaml_creates_the_file_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "cold_case_ok.yaml"
    scaffold.append_source_yaml(
        path,
        {"source_key": "cold_case_ok_osbi_2026_08_31", "adapter_name": "cold_case_ok_osbi"},
    )
    data = yaml.safe_load(path.read_text())
    assert len(data["sources"]) == 1


def test_append_source_yaml_replaces_an_entry_with_the_same_adapter_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cold_case_ok.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "source_key": "cold_case_ok_osbi_2026_07_08",
                        "adapter_name": "cold_case_ok_osbi",
                    }
                ]
            }
        )
    )
    scaffold.append_source_yaml(
        path,
        {"source_key": "cold_case_ok_osbi_2026_08_31", "adapter_name": "cold_case_ok_osbi"},
    )
    sources = yaml.safe_load(path.read_text())["sources"]
    assert len(sources) == 1
    assert sources[0]["source_key"] == "cold_case_ok_osbi_2026_08_31"


def test_append_source_yaml_keeps_unrelated_entries(tmp_path: Path) -> None:
    path = tmp_path / "cold_case_md.yaml"
    path.write_text(yaml.safe_dump({"sources": [{"adapter_name": "cold_case_md_harford"}]}))
    scaffold.append_source_yaml(path, {"adapter_name": "cold_case_md_howard"})
    assert len(yaml.safe_load(path.read_text())["sources"]) == 2


def test_append_source_yaml_refuses_an_entry_with_no_adapter_name(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldRefusal, match="no adapter_name"):
        scaffold.append_source_yaml(tmp_path / "x.yaml", {"source_key": "k"})


def test_register_adapter_adds_import_and_registration_once(tmp_path: Path) -> None:
    path = tmp_path / "run_pipeline.py"
    path.write_text(
        "from casesignal.etl.adapters.cold_case_va.adapter import ColdCaseVAAdapter\n"
        "\n"
        "def build_registry():\n"
        "    registry.register(ColdCaseVAAdapter)\n"
        "    return registry\n"
    )
    scaffold.register_adapter(path, "cold_case_ok_osbi", "ColdCaseOKOSBIAdapter")
    scaffold.register_adapter(path, "cold_case_ok_osbi", "ColdCaseOKOSBIAdapter")

    text = path.read_text()
    assert text.count("ColdCaseOKOSBIAdapter") == 2  # one import, one registration
    assert "registry.register(ColdCaseOKOSBIAdapter)" in text


def test_register_adapter_inserts_the_import_in_sorted_position(tmp_path: Path) -> None:
    """The repo lints with ruff's isort rule; an appended import is a red CI run."""
    path = tmp_path / "run_pipeline.py"
    path.write_text(
        "from casesignal.etl.adapters.cold_case_co.adapter import ColdCaseCOAdapter\n"
        "from casesignal.etl.adapters.cold_case_va.adapter import ColdCaseVAAdapter\n"
        "\n"
        "def build_registry():\n"
        "    registry.register(ColdCaseCOAdapter)\n"
        "    registry.register(ColdCaseVAAdapter)\n"
    )
    scaffold.register_adapter(path, "cold_case_ok_osbi", "ColdCaseOkOsbiAdapter")
    lines = path.read_text().splitlines()
    modules = [line for line in lines if line.startswith("from casesignal.etl.adapters")]
    assert modules == sorted(modules)
    # ...and the registration goes last, because that list is chronological.
    assert lines[-1].strip() == "registry.register(ColdCaseOkOsbiAdapter)"


def test_register_adapter_does_not_count_a_longer_name_as_already_present(
    tmp_path: Path,
) -> None:
    """Presence is a whole word. A substring test reads a longer class as this one."""
    path = tmp_path / "run_pipeline.py"
    path.write_text(
        "from casesignal.etl.adapters.cold_case_md_howard_v2.adapter import (\n"
        "    ColdCaseMdHowardAdapterV2,\n"
        ")\n"
        "\n"
        "def build_registry():\n"
        "    registry.register(ColdCaseMdHowardAdapterV2)\n"
    )
    scaffold.register_adapter(path, "cold_case_md_howard", "ColdCaseMdHowardAdapter")
    assert "registry.register(ColdCaseMdHowardAdapter)" in path.read_text()


def test_register_adapter_refuses_a_file_with_no_registry(tmp_path: Path) -> None:
    path = tmp_path / "run_pipeline.py"
    path.write_text("from casesignal.etl.adapters.cold_case_va.adapter import A\n")
    with pytest.raises(ScaffoldRefusal, match="registry.register"):
        scaffold.register_adapter(path, "cold_case_ok_osbi", "ColdCaseOkOsbiAdapter")


def test_the_real_run_pipeline_is_still_shaped_the_way_the_edit_assumes() -> None:
    """The edit anchors on two literals in a hand-maintained file; pin them here."""
    text = (REPO_ROOT / "src/casesignal/etl/runners/run_pipeline.py").read_text()
    assert "from casesignal.etl.adapters.cold_case_va.adapter import" in text
    assert "    registry.register(ColdCaseVAAdapter)" in text


# --- obligation 4: the listing/record split ---


def test_invariant_tests_assert_the_derived_floors() -> None:
    rendered = scaffold.render_invariant_tests(make_brief())
    assert "0.95" in rendered
    assert "victim_age" in rendered
    assert "def test_listing_discovery_finds_every_record" in rendered
    assert "307" in rendered


def test_invariant_tests_skip_the_full_corpus_assertion_for_a_sample() -> None:
    rendered = scaffold.render_invariant_tests(
        make_brief(records_captured=50, records_total=None, listing_record_count=50)
    )
    assert "def test_listing_discovery_finds_every_record" not in rendered
    # The marker that stands where the skipped test would be, not merely the word
    # somewhere in the prose above it.
    assert (
        "# No exact-count assertion: this capture is a sampled corpus, not a" in rendered
    )


def test_a_census_render_never_calls_itself_a_sampled_corpus() -> None:
    assert "sampled corpus" not in scaffold.render_invariant_tests(make_brief())


def test_a_truncated_walk_is_not_a_census_even_at_an_equal_total() -> None:
    """records_total == records_captured is not enough: the walk must have finished."""
    rendered = scaffold.render_invariant_tests(make_brief(truncated=True))
    assert "sampled corpus" in rendered
    assert "def test_listing_discovery_finds_every_record" not in rendered


def test_the_always_rendered_invariants_are_all_present() -> None:
    rendered = scaffold.render_invariant_tests(make_brief())
    for name in (
        "def test_every_record_has_a_case_name",
        "def test_source_case_ids_are_unique",
        "def test_case_types_are_in_the_vocabulary",
        "def test_contact_line_does_not_bleed_into_narrative",
    ):
        assert name in rendered


# --- obligation 4b: a vacuous floor renders no test ---


def test_a_vacuous_floor_in_a_mixture_renders_no_coverage_test() -> None:
    rendered = scaffold.render_invariant_tests(
        make_brief(floors={"victim_age": 0.0, "county": 0.9})
    )
    assert "def test_coverage_floor_county" in rendered
    assert "def test_coverage_floor_victim_age" not in rendered
    assert "derived floor is 0.0" in rendered


def test_a_detail_page_floor_is_asserted_over_the_detail_records() -> None:
    rendered = scaffold.render_invariant_tests(
        make_brief(
            floors={"victim_age": 0.9},
            locators={"victim_age": {"kind": "css", "value": ".age", "page": "detail"}},
        )
    )
    assert '_coverage(detail_records, "victim_age")' in rendered


def test_a_list_page_floor_is_asserted_over_the_listing_records() -> None:
    rendered = scaffold.render_invariant_tests(make_brief())
    assert '_coverage(raw_listing_records, "victim_age")' in rendered


# --- obligations 2, 3, 7: expectations ---


def test_expectation_tests_remap_reader_vocabulary_to_adapter_vocabulary() -> None:
    rendered = scaffold.render_expectation_tests(
        [ExpectedRecord(record_key="a.html#0", values={"victim_name": "Jane", "age": "34"})],
        "cold_case_ok_osbi",
    )
    assert '"case_name": "Jane"' in rendered
    assert '"victim_age": "34"' in rendered
    assert "victim_name" not in rendered


def test_remapping_expectations_is_idempotent() -> None:
    once = scaffold.render_expectation_tests(
        [ExpectedRecord(record_key="a.html#0", values={"victim_name": "Jane"})], "x"
    )
    twice = scaffold.render_expectation_tests(
        [ExpectedRecord(record_key="a.html#0", values={"case_name": "Jane"})], "x"
    )
    assert once == twice


def test_the_expectation_count_is_recorded_and_a_thin_set_is_visible() -> None:
    rendered = scaffold.render_expectation_tests(
        [ExpectedRecord(record_key="a.html#0", values={"case_name": "Jane"})], "x"
    )
    assert "EXPECTED_RECORD_COUNT = 1" in rendered
    assert "def test_the_expectation_set_is_not_thin" in rendered
    assert f"MINIMUM_EXPECTATION_SET = {scaffold.MINIMUM_EXPECTATION_SET}" in rendered


def test_the_thin_set_assertion_actually_fails_for_one_record() -> None:
    """The generated guard has to go red, not merely exist."""
    rendered = scaffold.render_expectation_tests(
        [ExpectedRecord(record_key="a.html#0", values={"case_name": "Jane"})], "x"
    )
    namespace = _exec_generated(rendered)
    with pytest.raises(AssertionError, match="only 1 golden record"):
        namespace["test_the_expectation_set_is_not_thin"]()


def test_the_thin_set_assertion_passes_at_three_records() -> None:
    rendered = scaffold.render_expectation_tests(
        [
            ExpectedRecord(record_key=f"a.html#{index}", values={"case_name": "Jane"})
            for index in range(3)
        ],
        "x",
    )
    _exec_generated(rendered)["test_the_expectation_set_is_not_thin"]()


def test_record_keys_are_resolved_against_the_listing_fixture_they_name() -> None:
    """The key names the LISTING fixture even for a value read off a detail page."""
    rendered = scaffold.render_expectation_tests(
        [ExpectedRecord(record_key="range_a-b.html#12", values={"case_name": "Jane"})],
        "cold_case_ok_osbi",
    )
    assert '"range_a-b.html#12"' in rendered
    assert "replay(FIXTURES_ROOT, RUNTIME_SPEC, parse_records, parse_detail).records" in rendered
    assert "def test_every_expected_record_key_resolves" in rendered
    assert "def test_golden_range_a_b_html_12" in rendered


def test_duplicate_slugs_do_not_collide_into_one_test() -> None:
    rendered = scaffold.render_expectation_tests(
        [
            ExpectedRecord(record_key="a.html#1", values={"case_name": "A"}),
            ExpectedRecord(record_key="a-html#1", values={"case_name": "B"}),
        ],
        "x",
    )
    assert rendered.count("def test_golden_a_html_1(") == 1
    assert "def test_golden_a_html_1_x(" in rendered


# --- obligation 8: everything generated parses, and imports ---


def test_generated_modules_parse() -> None:
    brief = make_brief()
    ast.parse(scaffold.render_invariant_tests(brief))
    ast.parse(scaffold.render_expectation_tests([], "cold_case_ok_osbi"))


@pytest.fixture()
def importable_adapters(tmp_path: Path) -> Iterator[Path]:
    """Let ``casesignal.etl.adapters.<drafted>`` resolve inside tmp_path.

    ``__path__`` on a regular package is a plain list, so extending it makes the
    generated package genuinely importable under its real dotted name -- which is
    what obligation 8 asks about, since the drafted modules import each other by it.
    """
    package = importlib.import_module("casesignal.etl.adapters")
    root = tmp_path / "src/casesignal/etl/adapters"
    root.mkdir(parents=True, exist_ok=True)
    package.__path__.append(str(root))
    before = set(sys.modules)
    try:
        yield tmp_path
    finally:
        package.__path__.remove(str(root))
        for name in set(sys.modules) - before:
            del sys.modules[name]


def test_scaffold_writes_a_package_that_actually_imports(
    importable_adapters: Path, tmp_path: Path
) -> None:
    repo_root = importable_adapters
    _with_run_pipeline(repo_root)
    # A name no real adapter uses, so the tmp package is not shadowed by the
    # installed one when it resolves under the shared dotted path.
    brief = make_brief(
        adapter_name="cold_case_zz_draft",
        source_key="cold_case_zz_draft_2026_08_31",
        state="ZZ",
        expectations=(
            ExpectedRecord(record_key="range_a-b.html#0", values={"victim_name": "Jane"}),
        ),
    )
    written = scaffold.scaffold(brief, repo_root=repo_root)

    assert "src/casesignal/etl/adapters/cold_case_zz_draft/adapter.py" in written
    assert "src/casesignal/etl/sources/cold_case_zz.yaml" in written
    assert "docs/drafts/cold_case_zz_draft.md" in written

    module = importlib.import_module("casesignal.etl.adapters.cold_case_zz_draft.adapter")
    assert module.ColdCaseZzDraftAdapter.adapter_name == "cold_case_zz_draft"
    # raw_load imports the adapter's own floor lazily; register.py imports the
    # shared registration helper. Both must resolve for real.
    importlib.import_module("casesignal.etl.adapters.cold_case_zz_draft.register")
    importlib.import_module("casesignal.etl.adapters.cold_case_zz_draft.raw_load")

    for path in written:
        if path.endswith(".py"):
            ast.parse((repo_root / path).read_text())


def test_the_declared_targets_are_the_files_the_scaffold_actually_writes(
    tmp_path: Path,
) -> None:
    """`claim` pre-flights the overwrite refusal against the DECLARED list.

    A target the scaffold writes but the declaration omits would be written with nothing
    having checked it, and the hoisted refusal would silently stop covering it. The
    generator refuses on the mismatch rather than trusting the two lists to stay in step;
    this pins that they are in step today.
    """
    repo_root = _with_run_pipeline(tmp_path)
    written = scaffold.scaffold(make_brief(), repo_root=repo_root)
    declared = scaffold.generated_target_paths("cold_case_ok_osbi")

    assert written[: len(declared)] == declared
    # The two the declaration deliberately leaves out: both are APPENDED to rather than
    # written, so neither can be overwritten and neither belongs in an overwrite check.
    assert written[len(declared) :] == [
        "src/casesignal/etl/sources/cold_case_ok.yaml",
        "src/casesignal/etl/runners/run_pipeline.py",
    ]


def test_scaffold_is_idempotent_across_two_runs(importable_adapters: Path) -> None:
    repo_root = importable_adapters
    (repo_root / "src/casesignal/etl/runners").mkdir(parents=True, exist_ok=True)
    run_pipeline = repo_root / "src/casesignal/etl/runners/run_pipeline.py"
    run_pipeline.write_text(
        "from casesignal.etl.adapters.cold_case_va.adapter import ColdCaseVAAdapter\n"
        "\n"
        "def build_adapter_registry():\n"
        "    registry.register(ColdCaseVAAdapter)\n"
        "    return registry\n"
    )
    scaffold.scaffold(make_brief(), repo_root=repo_root)
    first = run_pipeline.read_text()
    assert first.count("ColdCaseOkOsbiAdapter") == 2
    scaffold.scaffold(
        make_brief(source_key="cold_case_ok_osbi_2026_09_09"), repo_root=repo_root
    )

    assert run_pipeline.read_text() == first
    sources = yaml.safe_load(
        (repo_root / "src/casesignal/etl/sources/cold_case_ok.yaml").read_text()
    )["sources"]
    assert len(sources) == 1
    assert sources[0]["source_key"] == "cold_case_ok_osbi_2026_09_09"


def test_the_generated_yaml_entry_loads_as_a_source_definition(
    importable_adapters: Path,
) -> None:
    from casesignal.etl.services.source_definition import SourceDefinition

    entry = scaffold.source_yaml_entry(make_brief())
    definition = SourceDefinition(
        source_key=entry["source_key"],
        source_family=entry["source_family"],
        adapter_name=entry["adapter_name"],
        source_code=entry["source_code"],
        source_name=entry["source_name"],
        input_path=entry["input_path"],
        input_type=entry["input_type"],
        source_year=entry["source_year"],
        source_state=entry["source_state"],
        description=entry["description"],
        metadata=entry["metadata"],
    )
    assert definition.adapter_name == "cold_case_ok_osbi"
    assert entry["source_code"] == "OSBI_OK"


def test_a_year_in_the_index_url_drops_the_source_year() -> None:
    """SourceDefinition refuses a source_year that contradicts the input path."""
    entry = scaffold.source_yaml_entry(
        make_brief(index_url="https://example.gov/cold-cases-2019/index.html")
    )
    assert entry["source_year"] is None


# --- obligation 6: the advisory reports reach the memo ---


def test_the_memo_surfaces_every_advisory_report() -> None:
    memo = scaffold.render_memo(
        make_brief(
            unreachable_floors=("victim_race",),
            vacuous_floors=("county",),
            suspected_page_mismatch=("narrative",),
            omission_rate=0.25,
            omitted_fields=("photo", "city"),
            requested_fields=("victim_age", "photo", "city", "county"),
        )
    )
    assert "**Unreachable floors** (1): `victim_race`" in memo
    assert "**Vacuous floors** (1): `county`" in memo
    assert "**Suspected page mismatch** (1): `narrative`" in memo
    assert "**Omission rate**: 0.25 -- 2 of the 4" in memo
    assert "namely `photo`, `city`" in memo


def test_the_memo_carries_the_source_facts_and_not_a_plan() -> None:
    memo = scaffold.render_memo(make_brief())
    for heading in (
        "## Identity",
        "## Page shapes",
        "## Corpus",
        "## Measured field inventory",
        "## Id strategy",
        "## Capture gotchas",
    ):
        assert heading in memo
    assert "The plan, the task breakdown and the ingest run-book are" in memo


def test_the_memo_names_a_thin_expectation_set() -> None:
    memo = scaffold.render_memo(
        make_brief(
            expectations=(ExpectedRecord(record_key="a#0", values={"case_name": "J"}),)
        )
    )
    assert "below the 3 the reader pass was asked for" in memo


# --- naming ---


def test_class_names_are_derived_by_one_rule() -> None:
    assert scaffold.class_name_for("cold_case_ok_osbi") == "ColdCaseOkOsbiAdapter"
    assert scaffold.class_name_for("cold_case_md_baltimore_county") == (
        "ColdCaseMdBaltimoreCountyAdapter"
    )


def test_source_codes_follow_the_agency_then_state_shape() -> None:
    assert scaffold.source_code_for("cold_case_ok_osbi", "OK") == "OSBI_OK"
    assert scaffold.source_code_for("cold_case_md_howard", "MD") == "HOWARD_MD"


def test_the_templates_module_imports_nothing_outside_the_standard_library() -> None:
    """Templates are plain string formatting; jinja is not a project dependency."""
    tree = ast.parse((REPO_ROOT / "src/casesignal/drafter/templates.py").read_text())
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported <= {"__future__", "string"}


# --- shared files are edited, not reformatted ---


def test_register_adapter_keeps_the_files_own_line_endings(tmp_path: Path) -> None:
    """The working tree is CRLF (core.autocrlf=true); a rewrite to LF is a whole-file diff."""
    path = tmp_path / "run_pipeline.py"
    body = (
        "from casesignal.etl.adapters.cold_case_va.adapter import ColdCaseVAAdapter\r\n"
        "\r\n"
        "def build_registry():\r\n"
        "    registry.register(ColdCaseVAAdapter)\r\n"
    )
    path.write_bytes(body.encode("utf-8"))
    scaffold.register_adapter(path, "cold_case_zz_draft", "ColdCaseZzDraftAdapter")

    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert b"    registry.register(ColdCaseZzDraftAdapter)\r\n" in raw


def test_append_source_yaml_keeps_the_files_own_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "cold_case_ok.yaml"
    path.write_bytes(b"sources:\r\n  - adapter_name: cold_case_ok_osbi\r\n")
    scaffold.append_source_yaml(path, {"adapter_name": "cold_case_ok_other"})

    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_a_template_that_would_emit_broken_python_is_refused(
    importable_adapters: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parse guard fires before anything is written, not after."""
    from string import Template

    from casesignal.drafter import templates

    monkeypatch.setattr(templates, "REGISTER_PY", Template("def (:\n"))
    with pytest.raises(ScaffoldRefusal, match="does not parse"):
        scaffold.scaffold(make_brief(), repo_root=importable_adapters)
    assert not (
        importable_adapters / "src/casesignal/etl/adapters/cold_case_ok_osbi"
    ).exists()


# --- identity values that decide a path, a filename, or a SQL identifier ---


@pytest.mark.parametrize(
    "state",
    [
        "x/../../../../../../ESCAPED",
        "OK'; DROP TABLE x; --",
        "O",
        "OKL",
        "  ",
        "..",
    ],
)
def test_a_state_that_is_not_a_postal_code_is_refused(state: str) -> None:
    """`state` names the catalog file this generator writes, and arrives untyped.

    The classifier schema for it is `{"type": ["string", "null"]}` -- no pattern, no
    enum -- so a traversal string is a valid verdict all the way to a write path.
    """
    with pytest.raises(ScaffoldRefusal, match="two-letter postal code"):
        make_brief(state=state)


def test_a_traversing_state_cannot_reach_a_path_outside_repo_root(tmp_path: Path) -> None:
    escape = tmp_path / "escaped.yaml"
    with pytest.raises(ScaffoldRefusal):
        scaffold.scaffold(
            make_brief(state="x/../../../../../../../.." + str(tmp_path) + "/escaped"),
            repo_root=tmp_path / "repo",
        )
    assert not escape.exists()


@pytest.mark.parametrize(
    "adapter_name",
    [
        "../../../../tmp/pwned",
        "ColdCaseZZ",
        "cold_case_zz_ünï",
        "9lives",
        "cold case zz",
        "c" * 65,
    ],
)
def test_an_adapter_name_outside_the_house_form_is_refused(adapter_name: str) -> None:
    with pytest.raises(ScaffoldRefusal, match="adapter_name"):
        make_brief(adapter_name=adapter_name)


def test_a_field_name_over_the_postgres_identifier_limit_is_refused() -> None:
    with pytest.raises(ScaffoldRefusal, match="63-byte identifier limit"):
        make_brief(floors={"v" * 64: 0.9})


def test_two_field_names_sharing_a_63_byte_prefix_cannot_reach_the_table() -> None:
    """Both would truncate to one column; the length bound refuses them first.

    Kept as its own test because the reported failure was the pair, not either name:
    the bound is what makes the collision unreachable, so the bound is what is pinned.
    """
    prefix = "v" * 63
    with pytest.raises(ScaffoldRefusal, match="63-byte identifier limit"):
        make_brief(floors={f"{prefix}_a": 0.9, f"{prefix}_b": 0.9})


# --- the catalog is edited by line, not round-tripped ---


def test_append_source_yaml_leaves_every_other_line_byte_identical(
    tmp_path: Path,
) -> None:
    """The real file, with its folded descriptions, quoted dates and blank separators."""
    real = REPO_ROOT / "src/casesignal/etl/sources/cold_case_md.yaml"
    path = tmp_path / "cold_case_md.yaml"
    path.write_bytes(real.read_bytes())
    before = path.read_bytes().splitlines(keepends=True)

    scaffold.append_source_yaml(
        path, scaffold.source_yaml_entry(make_brief(adapter_name="cold_case_md_frederick"))
    )

    after = path.read_bytes().splitlines(keepends=True)
    assert after[: len(before)] == before, "an existing line was rewritten"
    assert yaml.safe_load(path.read_bytes())["sources"][:-1] == yaml.safe_load(
        real.read_bytes()
    )["sources"]


def _entry_line_span(text: str, adapter_name: str) -> tuple[int, int]:
    """Locate one entry's lines independently of the implementation being tested."""
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith("  - ")]
    for position, start in enumerate(starts):
        stop = starts[position + 1] if position + 1 < len(starts) else len(lines)
        if any(line.strip() == f"adapter_name: {adapter_name}" for line in lines[start:stop]):
            return start, stop
    raise AssertionError(f"no entry for {adapter_name}")


def test_append_source_yaml_replaces_only_the_matching_entrys_lines(
    tmp_path: Path,
) -> None:
    """Three things, because two of them alone let a partial replacement through.

    PyYAML resolves duplicate keys last-wins, so leaving the old entry's tail in place
    still parses: the file grows by 21 lines and the entry becomes a mixture with the
    new source_key over the old source_code, source_name, description and metadata,
    and an assertion that only counts entries and compares the OTHERS sees nothing.
    So the replaced entry is compared to the entry that was passed, and the file's
    length is compared to the length it must have.
    """
    real = REPO_ROOT / "src/casesignal/etl/sources/cold_case_md.yaml"
    path = tmp_path / "cold_case_md.yaml"
    path.write_bytes(real.read_bytes())
    before = real.read_text()
    before_lines = before.splitlines(keepends=True)
    start, stop = _entry_line_span(before, "cold_case_md_howard")
    old_blanks = sum(
        1 for line in reversed(before_lines[start:stop]) if not line.strip()
    )

    entry = scaffold.source_yaml_entry(make_brief(adapter_name="cold_case_md_howard"))
    scaffold.append_source_yaml(path, entry)

    after = path.read_text()
    sources = yaml.safe_load(path.read_bytes())["sources"]
    assert len(sources) == 6

    # 1. the untouched entries are untouched
    kept = [e for e in sources if e["adapter_name"] != "cold_case_md_howard"]
    original = [
        e
        for e in yaml.safe_load(real.read_bytes())["sources"]
        if e["adapter_name"] != "cold_case_md_howard"
    ]
    assert kept == original

    # 2. the replaced entry IS the entry that was passed, not a mixture of old and new
    replaced = next(e for e in sources if e["adapter_name"] == "cold_case_md_howard")
    assert replaced == entry

    # 3. the file is exactly as long as a clean swap makes it -- no leftover tail, no
    #    eaten separator
    rendered = scaffold.render_source_yaml_entry(entry).splitlines(keepends=True)
    assert len(after.splitlines(keepends=True)) == (
        len(before_lines) - (stop - start) + len(rendered) + old_blanks
    )
    assert after.count("\n\n") == before.count("\n\n")


def test_the_rendered_entry_is_in_the_catalogs_house_style() -> None:
    rendered = scaffold.render_source_yaml_entry(scaffold.source_yaml_entry(make_brief()))
    lines = rendered.splitlines()
    assert lines[0].startswith("  - source_key: ")
    assert lines[1] == "    source_family: cold_case"
    assert "    description: >-" in lines
    assert any(line.startswith("      source_url: ") for line in lines)


def test_the_rendered_entry_matches_the_indent_of_the_file_it_joins(
    tmp_path: Path,
) -> None:
    """PyYAML's own default is indentless; splicing at the wrong indent breaks parsing."""
    path = tmp_path / "cold_case_ok.yaml"
    path.write_text(yaml.safe_dump({"sources": [{"adapter_name": "cold_case_ok_other"}]}))
    scaffold.append_source_yaml(path, {"adapter_name": "cold_case_ok_osbi"})
    assert len(yaml.safe_load(path.read_text())["sources"]) == 2


def test_the_catalog_entry_keys_are_the_declared_order() -> None:
    """One statement of the key order, shared by the builder and the renderer."""
    from casesignal.drafter import templates

    assert tuple(scaffold.source_yaml_entry(make_brief())) == templates.SOURCE_YAML_ENTRY_KEYS


# --- a draft never overwrites hand-written work ---


def test_every_written_file_ends_in_a_verifying_marker_line(
    importable_adapters: Path,
) -> None:
    """The marker is what tells a drafted file from a hand-written one; nothing else."""
    repo_root = _with_run_pipeline(importable_adapters)
    shared = {
        "src/casesignal/etl/runners/run_pipeline.py",
        "src/casesignal/etl/sources/cold_case_ok.yaml",
    }
    generated = [p for p in scaffold.scaffold(make_brief(), repo_root=repo_root) if p not in shared]
    assert len(generated) == 7
    for path in generated:
        text = (repo_root / path).read_text()
        assert scaffold.is_generated_by_us(text), path
        assert text.splitlines()[-1].lstrip().startswith(("# drafted-by:", "<!-- drafted-by:"))


def test_the_memos_marker_is_an_html_comment(importable_adapters: Path) -> None:
    repo_root = _with_run_pipeline(importable_adapters)
    scaffold.scaffold(make_brief(), repo_root=repo_root)
    memo = (repo_root / "docs/drafts/cold_case_ok_osbi.md").read_text()
    assert memo.splitlines()[-1].startswith("<!-- drafted-by: ")
    assert memo.splitlines()[-1].endswith(" -->")


def test_scaffold_refuses_to_overwrite_a_hand_written_adapter(
    importable_adapters: Path,
) -> None:
    repo_root = importable_adapters
    package = repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi"
    package.mkdir(parents=True)
    handwritten = package / "adapter.py"
    handwritten.write_text('"""Hand-written OK OSBI adapter."""\n')

    with pytest.raises(ScaffoldRefusal, match="is not an unmodified product"):
        scaffold.scaffold(make_brief(), repo_root=repo_root)

    assert handwritten.read_text() == '"""Hand-written OK OSBI adapter."""\n'
    assert not (repo_root / "docs/drafts/cold_case_ok_osbi.md").exists()


def test_scaffold_refuses_a_hand_written_catalog_entry(
    importable_adapters: Path,
) -> None:
    repo_root = importable_adapters
    catalog = repo_root / "src/casesignal/etl/sources/cold_case_ok.yaml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        "sources:\n"
        "  - source_key: cold_case_ok_osbi_2026_07_08\n"
        "    adapter_name: cold_case_ok_osbi\n"
    )
    with pytest.raises(ScaffoldRefusal, match="this generator did not write"):
        scaffold.scaffold(make_brief(), repo_root=repo_root)


def test_a_re_draft_of_the_generators_own_output_is_allowed(
    importable_adapters: Path,
) -> None:
    repo_root = importable_adapters
    _with_run_pipeline(repo_root)
    scaffold.scaffold(make_brief(), repo_root=repo_root)
    scaffold.scaffold(make_brief(), repo_root=repo_root)  # no refusal


# --- numbers and vocabularies the templates carry ---


def test_the_minimum_expected_case_count_sits_a_fifth_below_the_capture() -> None:
    """The one derived number in the template, and the adapter's ingest guard."""
    assert scaffold._min_expected_cases(make_brief(records_captured=307)) == 245
    assert scaffold._min_expected_cases(make_brief(records_captured=10)) == 8
    assert scaffold._min_expected_cases(make_brief(records_captured=1)) == 1


def test_the_minimum_expected_count_reaches_the_generated_adapter(
    importable_adapters: Path,
) -> None:
    repo_root = importable_adapters
    _with_run_pipeline(repo_root)
    scaffold.scaffold(make_brief(records_captured=307), repo_root=repo_root)
    adapter = (
        repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi/adapter.py"
    ).read_text()
    assert "_MIN_EXPECTED_CASES = 245" in adapter


def test_the_contact_markers_reach_the_generated_bleed_test() -> None:
    """The bleed test's whole detection vocabulary; a nonsense marker detects nothing."""
    from casesignal.drafter import templates

    assert "if you have any information" in templates.CONTACT_MARKERS
    assert "anyone with information" in templates.CONTACT_MARKERS
    assert "please contact" in templates.CONTACT_MARKERS
    rendered = scaffold.render_invariant_tests(make_brief())
    for marker in templates.CONTACT_MARKERS:
        assert f'"{marker}"' in rendered


def test_a_vacuous_floor_still_gets_a_raw_column(importable_adapters: Path) -> None:
    """No coverage test, but the column has to exist or the parser cannot write it."""
    repo_root = importable_adapters
    _with_run_pipeline(repo_root)
    scaffold.scaffold(
        make_brief(floors={"victim_age": 0.95, "county": 0.0}), repo_root=repo_root
    )
    raw_load = (
        repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi/raw_load.py"
    ).read_text()
    assert "county             TEXT," in raw_load
    assert '"county": entry.get("county"),' in raw_load


def test_the_invariant_headers_listing_claim_matches_the_capture() -> None:
    """A fixed 'walked exhaustively' sentence above a 'not a census' note contradicts."""
    # Normalised, because the paragraph is wrapped: the claim is what it says, not
    # where the lines break.
    census = " ".join(scaffold.render_invariant_tests(make_brief()).split())
    assert "The capture walked the listing exhaustively" in census

    sample = " ".join(
        scaffold.render_invariant_tests(make_brief(truncated=True)).split()
    )
    assert "The capture walked the listing exhaustively" not in sample
    assert "because the listing was NOT walked exhaustively" in sample


# --- the marker is a digest, not a phrase ---


def test_a_hand_edited_generated_file_is_not_overwritten(
    importable_adapters: Path,
) -> None:
    """The case the phrase check got wrong: our own output, edited in the workflow.

    A drafted file a human edits keeps every word of the drafter's prose, so a
    substring test still called it regenerable and replaced the edit with a stub.
    """
    repo_root = _with_run_pipeline(importable_adapters)
    scaffold.scaffold(make_brief(), repo_root=repo_root)
    adapter = repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi/adapter.py"
    lines = adapter.read_text().splitlines(keepends=True)
    # Inserted ABOVE the marker line, which is where a human edit actually goes. An
    # edit appended after the marker would be refused merely for displacing it, and
    # would never exercise the digest at all.
    edited = "".join(lines[:-1]) + "# a human worked here\n" + lines[-1]
    adapter.write_text(edited)
    assert scaffold.is_generated_by_us(adapter.read_text()) is False

    with pytest.raises(ScaffoldRefusal, match="is not an unmodified product"):
        scaffold.scaffold(make_brief(), repo_root=repo_root)
    assert adapter.read_text() == edited


def test_a_reworded_package_that_still_names_the_drafter_is_not_overwritten(
    importable_adapters: Path,
) -> None:
    """Prose in the body cannot forge the marker; only the digest can satisfy it."""
    repo_root = importable_adapters
    package = repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi"
    package.mkdir(parents=True)
    for name in ("__init__.py", "adapter.py", "register.py", "raw_load.py"):
        (package / name).write_text(
            '"""Originally drafted by the SP2 Adapter Drafter, then rewritten."""\n'
        )

    with pytest.raises(ScaffoldRefusal, match="is not an unmodified product"):
        scaffold.scaffold(make_brief(), repo_root=repo_root)
    assert (package / "adapter.py").read_text().startswith('"""Originally drafted')


def test_a_re_draft_from_a_different_brief_is_still_allowed(
    importable_adapters: Path,
) -> None:
    """The old file's own digest proves nobody touched it, whatever the new brief says."""
    repo_root = _with_run_pipeline(importable_adapters)
    scaffold.scaffold(make_brief(session_id="sess-1"), repo_root=repo_root)
    scaffold.scaffold(
        make_brief(session_id="sess-2", captured_at="2026-12-25T00:00:00Z"),
        repo_root=repo_root,
    )
    adapter = (
        repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi/adapter.py"
    ).read_text()
    assert "sess-2" in adapter.splitlines()[-1]


def test_the_digest_survives_a_crlf_checkout(importable_adapters: Path) -> None:
    """core.autocrlf=true hands back CRLF; a byte digest would refuse an untouched file."""
    repo_root = _with_run_pipeline(importable_adapters)
    scaffold.scaffold(make_brief(), repo_root=repo_root)
    adapter = repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi/adapter.py"
    lf = adapter.read_bytes()
    adapter.write_bytes(lf.replace(b"\n", b"\r\n"))

    # decode(), not read_text(): universal newlines would translate the CRLF away and
    # the test would pass without the normalisation it exists to pin.
    on_disk = adapter.read_bytes().decode("utf-8")
    assert "\r\n" in on_disk
    assert scaffold.is_generated_by_us(on_disk)
    scaffold.scaffold(make_brief(), repo_root=repo_root)  # no refusal


def test_a_truncated_marker_line_does_not_verify() -> None:
    body = "print(1)\n"
    stamped = scaffold.stamp_generated(
        body, path="x.py", session_id="s", captured_at="t"
    )
    assert scaffold.is_generated_by_us(stamped)
    assert not scaffold.is_generated_by_us(stamped[:-5] + "\n")
    assert not scaffold.is_generated_by_us(stamped + "print(2)\n")
    assert not scaffold.is_generated_by_us("")


# --- the splice reads YAML structure, not any line that starts with a dash ---


def test_a_nested_block_sequence_is_not_read_as_a_catalog_entry(
    tmp_path: Path,
) -> None:
    """cold_case_va.yaml carries `required_files:` with a `- raw_data.csv` item.

    Matching that as an entry ended the real entry's span early; replacing the entry
    then left the tail of it dangling and the file no longer parsed.
    """
    real = REPO_ROOT / "src/casesignal/etl/sources/cold_case_va.yaml"
    assert "\n      - raw_data.csv\n" in real.read_text(), "fixture premise changed"

    for adapter_name, expected in (("cold_case_va_fairfax", 2), ("cold_case_va", 1)):
        path = tmp_path / f"{adapter_name}.yaml"
        path.write_bytes(real.read_bytes())
        scaffold.append_source_yaml(
            path,
            scaffold.source_yaml_entry(
                make_brief(adapter_name=adapter_name, state="VA")
            ),
        )
        loaded = yaml.safe_load(path.read_bytes())  # ParserError before the fix
        assert len(loaded["sources"]) == expected, adapter_name


def test_a_description_line_beginning_with_a_dash_is_not_read_as_an_entry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cold_case_ok.yaml"
    path.write_text(
        "sources:\n"
        "  - adapter_name: cold_case_ok_first\n"
        "    description: >-\n"
        "      a wrapped description whose next line begins with\n"
        "      - a dash, which is prose, not a catalog entry\n"
    )
    scaffold.append_source_yaml(path, {"adapter_name": "cold_case_ok_first"})
    loaded = yaml.safe_load(path.read_text())
    assert len(loaded["sources"]) == 1
    assert loaded["sources"][0] == {"adapter_name": "cold_case_ok_first"}


def test_an_empty_flow_sequence_header_is_converted_before_splicing(
    tmp_path: Path,
) -> None:
    """`sources: []` is an empty sequence; block items cannot be spliced under it."""
    path = tmp_path / "cold_case_ok.yaml"
    path.write_text("sources: []\n")
    scaffold.append_source_yaml(path, {"adapter_name": "cold_case_ok_osbi"})
    loaded = yaml.safe_load(path.read_text())  # ParserError before the fix
    assert loaded["sources"] == [{"adapter_name": "cold_case_ok_osbi"}]


# --- the raw table identifier, not just its columns ---


def test_an_adapter_name_that_overflows_the_raw_table_identifier_is_refused() -> None:
    """`raw_cold_case.{adapter_name}_dv{N}` is one identifier, and Postgres truncates it."""
    at_limit = "c" * scaffold.ADAPTER_NAME_MAX
    make_brief(adapter_name=at_limit)  # accepted
    with pytest.raises(ScaffoldRefusal, match="raw_cold_case"):
        make_brief(adapter_name=at_limit + "c")
    assert scaffold.ADAPTER_NAME_MAX + len("_dv") + 9 <= 63


def test_a_body_that_was_not_stamped_is_refused_before_anything_is_written(
    importable_adapters: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The self-check: a stamping step that stops working disarms every future guard."""
    repo_root = _with_run_pipeline(importable_adapters)
    monkeypatch.setattr(
        scaffold, "stamp_generated", lambda body, **_: body  # noqa: ARG005
    )
    with pytest.raises(ScaffoldRefusal, match="does not end in a valid marker line"):
        scaffold.scaffold(make_brief(), repo_root=repo_root)
    assert not (repo_root / "src/casesignal/etl/adapters/cold_case_ok_osbi").exists()


def test_the_marker_line_is_spaced_the_way_the_formatter_wants_it() -> None:
    """black takes two blank lines after a def and one after a docstring.

    Guessing produced the one generated file that reformatted on its first format run,
    which is a diff on a file nobody edited.
    """
    after_def = scaffold.stamp_generated(
        'def f() -> None:\n    pass\n', path="a.py", session_id="s", captured_at="t"
    )
    assert after_def.splitlines()[-3:-1] == ["", ""]
    assert scaffold.is_generated_by_us(after_def)

    after_docstring = scaffold.stamp_generated(
        '"""A package."""\n', path="a.py", session_id="s", captured_at="t"
    )
    assert after_docstring.splitlines()[-2] == ""
    assert after_docstring.splitlines()[-3] == '"""A package."""'
    assert scaffold.is_generated_by_us(after_docstring)
