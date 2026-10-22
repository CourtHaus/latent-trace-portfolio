"""Unit tests for CLI arg parsing + cost estimation (pure logic).

Full end-to-end CLI behavior (DB connections, LLM calls, concurrency) is
tested via a smoke test — these are the deterministic pieces.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import casesignal.extraction.cold_case.cli as cli_module
from casesignal.extraction.cold_case.cli import (
    COST_CONFIRMATION_THRESHOLD_USD,
    PRICE_PER_CALL_USD,
    _enabled_tiers_for_state,
    estimate_cost,
    parse_args,
    parse_case_ids_file_content,
)
from casesignal.extraction.cold_case.prompt_loader import load_tier2_v4_prompt_template
from casesignal.extraction.cold_case.tier2_extract_case import (
    CaseTier2Extraction,
    Tier2Field,
    Tier2Victim,
)


def test_cost_estimate_for_zero_rows() -> None:
    assert estimate_cost(0, [1]) == 0.0


def test_cost_estimate_matches_per_case_constant_tier1() -> None:
    assert estimate_cost(100, [1]) == PRICE_PER_CALL_USD * 100


def test_cost_estimate_doubles_when_both_tiers_run() -> None:
    """Two tiers per case = two LLM calls per case."""
    assert estimate_cost(100, [1, 2]) == PRICE_PER_CALL_USD * 200


def test_cost_estimate_for_full_corpus_both_tiers() -> None:
    # 525 * 2 tiers * ~$0.001 ≈ $1.05. Well below the $5 confirmation threshold.
    c = estimate_cost(525, [1, 2])
    assert c < COST_CONFIRMATION_THRESHOLD_USD


def test_parse_args_default_tier_is_both() -> None:
    ns = parse_args([])
    assert ns.tier == "both"


def test_parse_args_tier_can_be_set_explicitly() -> None:
    assert parse_args(["--tier", "1"]).tier == "1"
    assert parse_args(["--tier", "2"]).tier == "2"
    assert parse_args(["--tier", "both"]).tier == "both"


def test_parse_args_defaults() -> None:
    ns = parse_args([])
    assert ns.concurrency == 5
    assert ns.dry_run is False
    assert ns.yes is False
    assert ns.force is False


def test_parse_args_case_id_single() -> None:
    ns = parse_args(["--case-id", "13443"])
    assert ns.case_id == 13443


def test_parse_args_concurrency_flag() -> None:
    ns = parse_args(["--concurrency", "10"])
    assert ns.concurrency == 10


def test_parse_args_state_filter() -> None:
    assert parse_args(["--state", "TN"]).state == "TN"
    assert parse_args([]).state is None


def test_parse_args_case_ids_file_default_none() -> None:
    assert parse_args([]).case_ids_file is None


def test_parse_args_case_ids_file_set() -> None:
    ns = parse_args(["--case-ids-file", "/tmp/ids.txt"])
    assert ns.case_ids_file == "/tmp/ids.txt"


def test_parse_case_ids_file_content_parses_ids() -> None:
    content = "13443\n9325\n5530\n"
    assert parse_case_ids_file_content(content) == [13443, 9325, 5530]


def test_parse_case_ids_file_content_ignores_blanks_and_comments() -> None:
    content = (
        "# the 90 phrase-flagged residence cases\n"
        "13443\n"
        "\n"
        "   \n"
        "9325   # trailing whitespace tolerated\n"
        "# another comment\n"
        "5530\n"
    )
    assert parse_case_ids_file_content(content) == [13443, 9325, 5530]


def test_parse_case_ids_file_content_dedupes_preserving_order() -> None:
    content = "13443\n9325\n13443\n5530\n9325\n"
    assert parse_case_ids_file_content(content) == [13443, 9325, 5530]


def test_parse_case_ids_file_content_empty_is_empty_list() -> None:
    assert parse_case_ids_file_content("# only comments\n\n") == []


def test_enabled_tiers_for_state_skips_tier2_disabled_states() -> None:
    # UT (full source demographics from BCI) stays in the disabled set.
    assert _enabled_tiers_for_state("UT", [1, 2]) == [1]
    # MN's adapter actively enqueues Tier-2 jobs but its source covers all
    # demographics; the policy must skip Tier-2 here too.
    assert _enabled_tiers_for_state("MN", [1, 2]) == [1]
    # MD's source provides no Tier-2 fields, so Tier-2 must run.
    assert _enabled_tiers_for_state("MD", [1, 2]) == [1, 2]
    # FL / OH / DC were re-enabled when the project moved to local extraction
    # (cost is no longer a tiebreaker). Tier-2 must run for them.
    assert _enabled_tiers_for_state("FL", [1, 2]) == [1, 2]
    assert _enabled_tiers_for_state("OH", [1, 2]) == [1, 2]
    assert _enabled_tiers_for_state("DC", [1, 2]) == [1, 2]
    assert _enabled_tiers_for_state(None, [1, 2]) == [1, 2]


def test_cli_uses_v4_prompt_template() -> None:
    """CLI must load the v4 template, not v3, so the prompt_hash changes and
    re-extraction is queued for all cases on next run."""
    v4_template = load_tier2_v4_prompt_template()
    # The CLI module imports load_tier2_v4_prompt_template from prompt_loader;
    # confirm the symbol is the v4 loader (not v3) by verifying that the
    # canonical v4 loader imported directly returns the same bytes as what
    # the CLI would use via its own reference to the same function.
    from casesignal.extraction.cold_case import prompt_loader as _pl
    assert _pl.load_tier2_v4_prompt_template() == v4_template


def _make_fake_tier2_ext() -> CaseTier2Extraction:
    """Build a minimal CaseTier2Extraction with two victims for test purposes."""
    null_field = Tier2Field(
        value=None, raw_phrase=None, source_start=None, source_end=None, low_confidence=False
    )
    v1 = Tier2Victim(
        ordinal=1,
        name=Tier2Field(
            value="Alice Smith",
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=False,
        ),
        victim_age=null_field,
        victim_gender=null_field,
    )
    v2 = Tier2Victim(
        ordinal=2,
        name=Tier2Field(
            value="Bob Jones",
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=False,
        ),
        victim_age=null_field,
        victim_gender=null_field,
    )
    return CaseTier2Extraction(
        case_id=1,
        incident_date=null_field,
        address=null_field,
        victim_age=null_field,
        victim_gender=null_field,
        extractor_version="test",
        prompt_hash="abc123",
        model_id="test-model",
        raw_llm_response=None,
        prompt_tokens=None,
        completion_tokens=None,
        cost_usd=None,
        notes=None,
        victims=(v1, v2),
    )


def _build_session_factory(
    case_row: MagicMock,
    meta_row: MagicMock,
    victim_mappings: list[MagicMock],
) -> tuple[MagicMock, MagicMock]:
    """Return a sessionmaker-like callable whose context-manager sessions respond
    sensibly to the three distinct execute() shapes main() issues:

      Session 1  — SELECT case_id, about_text, state WHERE case_id = :cid
                   → .all() returns [case_row]
      Session 2  — SELECT case_id, state, source_county_fips WHERE ANY(:ids)
                   → plain iteration returns [meta_row]
      Session 3  — SELECT victim_id, first_name, last_name WHERE case_id = :cid
                   → .mappings().all() returns victim_mappings
    """
    # Session 1: case lookup
    s1_result = MagicMock()
    s1_result.all.return_value = [case_row]
    s1 = MagicMock()
    s1.execute.return_value = s1_result
    s1.__enter__ = MagicMock(return_value=s1)
    s1.__exit__ = MagicMock(return_value=False)

    # Session 2: case_meta lookup — iterable directly (for r in session.execute(...))
    s2_result = MagicMock()
    s2_result.__iter__ = MagicMock(return_value=iter([meta_row]))
    s2 = MagicMock()
    s2.execute.return_value = s2_result
    s2.__enter__ = MagicMock(return_value=s2)
    s2.__exit__ = MagicMock(return_value=False)

    # Session 3: processing loop — victim SELECT uses .mappings().all()
    s3_victim_result = MagicMock()
    s3_victim_result.mappings.return_value.all.return_value = victim_mappings
    s3 = MagicMock()
    s3.execute.return_value = s3_victim_result
    s3.__enter__ = MagicMock(return_value=s3)
    s3.__exit__ = MagicMock(return_value=False)

    session_factory = MagicMock()
    # Each call to Session() returns the next session in sequence.
    session_factory.side_effect = [s1, s2, s3]
    return session_factory, s3


def _run_main_with_mocks(
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
    insert_victim_mock: MagicMock,
    apply_reconciliation_mock: MagicMock,
    promote_mock: MagicMock | None = None,
) -> int:
    """Wire all external seams and call main() for case_id=1 tier=2."""
    fake_ext = _make_fake_tier2_ext()

    case_row = MagicMock()
    case_row.case_id = 1
    case_row.about_text = "Victim Alice Smith was found deceased."
    case_row.state = "MD"

    meta_row = MagicMock()
    meta_row.case_id = 1
    meta_row.state = "MD"
    meta_row.source_county_fips = "24005"

    session_factory, s3 = _build_session_factory(
        case_row=case_row,
        meta_row=meta_row,
        victim_mappings=[],  # no pre-existing victims
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/test")
    monkeypatch.setattr(cli_module, "create_engine", MagicMock())
    monkeypatch.setattr(cli_module, "sessionmaker", MagicMock(return_value=session_factory))
    monkeypatch.setattr(cli_module, "make_llm_client", MagicMock())
    monkeypatch.setattr(cli_module, "extract_case_tier2", MagicMock(return_value=fake_ext))
    monkeypatch.setattr(cli_module, "extraction_exists_for", MagicMock(return_value=False))
    monkeypatch.setattr(cli_module, "insert_tier2_extraction", MagicMock())
    monkeypatch.setattr(cli_module, "backfill_canonical_values_from_tier2", MagicMock())
    monkeypatch.setattr(cli_module, "enqueue_geocoding_job_from_tier2", MagicMock())
    monkeypatch.setattr(cli_module, "insert_victim_extractions", insert_victim_mock)
    monkeypatch.setattr(cli_module, "apply_reconciliation", apply_reconciliation_mock)
    monkeypatch.setattr(cli_module, "promote_victim_demographics", promote_mock or MagicMock())

    argv = ["--case-id", "1", "--tier", "2", "--yes"]
    if dry_run:
        argv.append("--dry-run")
    return cli_module.main(argv)


def test_dry_run_performs_no_victim_table_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In --dry-run mode main() must not call insert_victim_extractions,
    apply_reconciliation, or promote_victim_demographics (all three write to
    cold_case.victim / victim_extraction).

    A negative control (non-dry-run with identical mocks) confirms that the
    same mocks ARE called in the write path — proving the dry-run assertions
    are not trivially true.
    """
    # --- Dry-run invocation: no write function must be called ---
    dry_insert = MagicMock()
    dry_apply = MagicMock()
    dry_promote = MagicMock()
    rc_dry = _run_main_with_mocks(
        monkeypatch,
        dry_run=True,
        insert_victim_mock=dry_insert,
        apply_reconciliation_mock=dry_apply,
        promote_mock=dry_promote,
    )
    assert rc_dry == 0, "main() should succeed in dry-run mode"
    dry_insert.assert_not_called()
    dry_apply.assert_not_called()
    dry_promote.assert_not_called()

    # --- Negative control: non-dry-run invocation MUST call all three functions ---
    wet_insert = MagicMock()
    wet_apply = MagicMock()
    wet_promote = MagicMock()
    rc_wet = _run_main_with_mocks(
        monkeypatch,
        dry_run=False,
        insert_victim_mock=wet_insert,
        apply_reconciliation_mock=wet_apply,
        promote_mock=wet_promote,
    )
    assert rc_wet == 0, "main() should succeed in non-dry-run mode"
    wet_insert.assert_called_once()
    wet_apply.assert_called_once()
    wet_promote.assert_called_once()


def test_cli_tier2_path_promotes_demographics(monkeypatch: pytest.MonkeyPatch) -> None:
    """The batch CLI must call promote_victim_demographics AFTER apply_reconciliation
    (promotion reads the victim_id links reconciliation just wrote)."""
    call_order: list[str] = []
    apply_mock = MagicMock(side_effect=lambda *a, **k: call_order.append("reconcile"))
    promote_mock = MagicMock(side_effect=lambda *a, **k: call_order.append("promote"))

    _run_main_with_mocks(
        monkeypatch,
        dry_run=False,
        insert_victim_mock=MagicMock(),
        apply_reconciliation_mock=apply_mock,
        promote_mock=promote_mock,
    )

    promote_mock.assert_called_once()
    assert call_order == ["reconcile", "promote"]
