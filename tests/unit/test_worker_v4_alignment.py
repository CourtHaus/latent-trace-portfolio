"""Unit tests for the worker-path v4 alignment (feat/worker-v4-roster).

Tests confirm:
  1. extraction_loop uses the v4 tier-2 prompt template loader (not v3).
  2. Each adapter that computes _TIER2_PROMPT_HASH uses v4.
  3. queue_handler Tier-2 branch calls insert_victim_extractions +
     apply_reconciliation — i.e. the roster persistence + reconciliation now
     matches the CLI path (cli.py) exactly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    load_tier2_v3_prompt_template,
    load_tier2_v4_prompt_template,
)

# ---------------------------------------------------------------------------
# 1. extraction_loop references v4, not v3
# ---------------------------------------------------------------------------

def test_extraction_loop_imports_v4_not_v3() -> None:
    """extraction_loop must import load_tier2_v4_prompt_template."""
    import casesignal.worker.extraction_loop as loop_mod
    assert hasattr(loop_mod, "load_tier2_v4_prompt_template"), (
        "extraction_loop must import load_tier2_v4_prompt_template"
    )
    assert not hasattr(loop_mod, "load_tier2_v3_prompt_template"), (
        "extraction_loop must NOT import load_tier2_v3_prompt_template (v3 is retired)"
    )


def test_extraction_loop_v4_template_differs_from_v3() -> None:
    """Sanity: the v4 hash must differ from v3 so new queue entries are created."""
    v3_hash = compute_prompt_hash(load_tier2_v3_prompt_template())
    v4_hash = compute_prompt_hash(load_tier2_v4_prompt_template())
    assert v3_hash != v4_hash, "v4 prompt must have a different hash from v3"


# ---------------------------------------------------------------------------
# 2. Adapter _TIER2_PROMPT_HASH constants use v4
# ---------------------------------------------------------------------------

def test_md_shared_adapter_uses_v4_hash() -> None:
    from casesignal.etl.adapters.cold_case_md_shared import transform_helpers
    expected = compute_prompt_hash(load_tier2_v4_prompt_template())
    assert transform_helpers._TIER2_PROMPT_HASH == expected, (
        "cold_case_md_shared._TIER2_PROMPT_HASH must match v4 hash"
    )


def test_nh_doj_adapter_uses_v4_hash() -> None:
    from casesignal.etl.adapters.cold_case_nh_doj import transform as nh_transform
    expected = compute_prompt_hash(load_tier2_v4_prompt_template())
    assert nh_transform._TIER2_PROMPT_HASH == expected, (
        "cold_case_nh_doj._TIER2_PROMPT_HASH must match v4 hash"
    )


def test_mn_bca_adapter_uses_v4_hash() -> None:
    from casesignal.etl.adapters.cold_case_mn_bca import transform as mn_transform
    expected = compute_prompt_hash(load_tier2_v4_prompt_template())
    assert mn_transform._TIER2_PROMPT_HASH == expected, (
        "cold_case_mn_bca._TIER2_PROMPT_HASH must match v4 hash"
    )


def test_fl_fdle_adapter_uses_v4_hash() -> None:
    from casesignal.etl.adapters.cold_case_fl_fdle import transform as fl_transform
    expected = compute_prompt_hash(load_tier2_v4_prompt_template())
    assert fl_transform._TIER2_PROMPT_HASH == expected, (
        "cold_case_fl_fdle._TIER2_PROMPT_HASH must match v4 hash"
    )


# ---------------------------------------------------------------------------
# 3. queue_handler Tier-2 branch now calls insert_victim_extractions +
#    apply_reconciliation (mirroring cli.py)
# ---------------------------------------------------------------------------

def _make_tier2_result() -> MagicMock:
    """Build a minimal mock CaseTier2Extraction with one victim."""
    victim = MagicMock()
    victim.ordinal = 1
    victim.name.value = "Jane Doe"

    ext = MagicMock()
    ext.case_id = 42
    ext.model_id = "test-model"
    ext.prompt_hash = "deadbeef"
    ext.address.value = None
    ext.victims = (victim,)
    ext.failed = False  # a successful extraction (not malformed)
    return ext


def _make_job(prompt_tier: int = 2) -> MagicMock:
    job = MagicMock()
    job.extraction_job_id = 7
    job.case_id = 42
    job.prompt_hash = "deadbeef"
    job.model_id = "test-model"
    job.prompt_tier = prompt_tier
    return job


def _make_session(victim_rows: list[dict[str, object]] | None = None) -> MagicMock:
    """Return a mock Session with predictable execute() return values.

    The handler calls session.execute() three times in the Tier-2 branch:
      1. SELECT about_text, state, source_county_fips  -> row (first())
      2. SELECT victim_id, first_name, last_name        -> .mappings().all()
      3. UPDATE extraction_job SET status='succeeded'  -> no return needed

    This factory wires all three so we can assert on the other patched calls
    (insert_victim_extractions, apply_reconciliation) without a real DB.
    """
    # Case row
    case_row = MagicMock()
    case_row.about_text = "Alice was found deceased on Main St."
    case_row.state = "MD"
    case_row.source_county_fips = "24005"

    # victim SELECT result
    victim_select = MagicMock()
    victim_select.mappings.return_value.all.return_value = (
        victim_rows if victim_rows is not None else []
    )

    session = MagicMock()

    # execute() is called multiple times; we need to dispatch by call.
    call_count: list[int] = [0]

    def _execute_dispatch(*_args: object, **_kwargs: object) -> MagicMock:
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            # SELECT about_text
            result = MagicMock()
            result.first.return_value = case_row
            return result
        elif idx == 1:
            # SELECT victim_id, first_name, last_name
            return victim_select
        else:
            # UPDATE extraction_job (and any subsequent)
            return MagicMock()

    session.execute.side_effect = _execute_dispatch
    # get_bind() is used in the except branch; not needed for happy path
    session.get_bind.return_value = MagicMock()
    return session


def test_queue_handler_tier2_calls_insert_victim_extractions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier-2 branch must call insert_victim_extractions(session, tier2_result)."""
    import casesignal.extraction.cold_case.queue_handler as qh

    fake_ext = _make_tier2_result()
    session = _make_session()
    job = _make_job(prompt_tier=2)

    insert_victim_mock = MagicMock()
    apply_mock = MagicMock()

    monkeypatch.setattr(qh, "extract_case_tier2", MagicMock(return_value=fake_ext))
    monkeypatch.setattr(qh, "extraction_exists_for", MagicMock(return_value=False))
    monkeypatch.setattr(qh, "insert_tier2_extraction", MagicMock())
    monkeypatch.setattr(qh, "backfill_canonical_values_from_tier2", MagicMock())
    monkeypatch.setattr(qh, "enqueue_geocoding_job_from_tier2", MagicMock())
    monkeypatch.setattr(qh, "insert_victim_extractions", insert_victim_mock)
    monkeypatch.setattr(qh, "plan_reconciliation", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(qh, "apply_reconciliation", apply_mock)
    monkeypatch.setattr(qh, "promote_victim_demographics", MagicMock())

    llm_client = MagicMock()
    qh.handle_extraction_job(
        session,
        job,
        llm_client=llm_client,
        tier1_prompt_template="t1",
        tier2_prompt_template="t2",
        model_id="test-model",
    )

    insert_victim_mock.assert_called_once_with(session, fake_ext)


def test_queue_handler_tier2_calls_apply_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier-2 branch must call apply_reconciliation with correct kwargs."""
    import casesignal.extraction.cold_case.queue_handler as qh

    fake_ext = _make_tier2_result()
    session = _make_session()
    job = _make_job(prompt_tier=2)

    fake_plan = MagicMock()
    apply_mock = MagicMock()

    monkeypatch.setattr(qh, "extract_case_tier2", MagicMock(return_value=fake_ext))
    monkeypatch.setattr(qh, "extraction_exists_for", MagicMock(return_value=False))
    monkeypatch.setattr(qh, "insert_tier2_extraction", MagicMock())
    monkeypatch.setattr(qh, "backfill_canonical_values_from_tier2", MagicMock())
    monkeypatch.setattr(qh, "enqueue_geocoding_job_from_tier2", MagicMock())
    monkeypatch.setattr(qh, "insert_victim_extractions", MagicMock())
    monkeypatch.setattr(qh, "plan_reconciliation", MagicMock(return_value=fake_plan))
    monkeypatch.setattr(qh, "apply_reconciliation", apply_mock)
    monkeypatch.setattr(qh, "promote_victim_demographics", MagicMock())

    llm_client = MagicMock()
    qh.handle_extraction_job(
        session,
        job,
        llm_client=llm_client,
        tier1_prompt_template="t1",
        tier2_prompt_template="t2",
        model_id="test-model",
    )

    apply_mock.assert_called_once_with(
        session,
        job.case_id,
        fake_plan,
        model_id=fake_ext.model_id,
        prompt_hash=fake_ext.prompt_hash,
    )


def test_queue_handler_tier1_does_not_call_victim_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier-1 jobs must NOT call insert_victim_extractions or apply_reconciliation."""
    import casesignal.extraction.cold_case.queue_handler as qh
    from casesignal.extraction.cold_case.extract_case import CaseExtraction

    fake_t1 = MagicMock(spec=CaseExtraction)
    fake_t1.failed = False  # a successful extraction (not malformed)
    session = MagicMock()

    # Session for Tier-1: only SELECT about_text + UPDATE
    case_row = MagicMock()
    case_row.about_text = "Some text."
    case_row.state = "MD"
    case_row.source_county_fips = "24005"

    call_count: list[int] = [0]

    def _dispatch(*_a: object, **_kw: object) -> MagicMock:
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            r = MagicMock()
            r.first.return_value = case_row
            return r
        return MagicMock()

    session.execute.side_effect = _dispatch

    insert_victim_mock = MagicMock()
    apply_mock = MagicMock()

    monkeypatch.setattr(qh, "extract_case", MagicMock(return_value=fake_t1))
    monkeypatch.setattr(qh, "extraction_exists_for", MagicMock(return_value=False))
    monkeypatch.setattr(qh, "insert_extraction", MagicMock())
    monkeypatch.setattr(qh, "insert_victim_extractions", insert_victim_mock)
    monkeypatch.setattr(qh, "apply_reconciliation", apply_mock)

    job = _make_job(prompt_tier=1)
    qh.handle_extraction_job(
        session,
        job,
        llm_client=MagicMock(),
        tier1_prompt_template="t1",
        tier2_prompt_template="t2",
        model_id="test-model",
    )

    insert_victim_mock.assert_not_called()
    apply_mock.assert_not_called()


def test_queue_handler_tier2_promotes_demographics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier-2 branch must call promote_victim_demographics AFTER reconciliation
    (promotion reads the victim_id links reconciliation just wrote)."""
    import casesignal.extraction.cold_case.queue_handler as qh

    fake_ext = _make_tier2_result()
    session = _make_session()
    job = _make_job(prompt_tier=2)

    call_order: list[str] = []
    apply_mock = MagicMock(side_effect=lambda *a, **k: call_order.append("reconcile"))
    promote_mock = MagicMock(side_effect=lambda *a, **k: call_order.append("promote"))

    monkeypatch.setattr(qh, "extract_case_tier2", MagicMock(return_value=fake_ext))
    monkeypatch.setattr(qh, "extraction_exists_for", MagicMock(return_value=False))
    monkeypatch.setattr(qh, "insert_tier2_extraction", MagicMock())
    monkeypatch.setattr(qh, "backfill_canonical_values_from_tier2", MagicMock())
    monkeypatch.setattr(qh, "enqueue_geocoding_job_from_tier2", MagicMock())
    monkeypatch.setattr(qh, "insert_victim_extractions", MagicMock())
    monkeypatch.setattr(qh, "plan_reconciliation", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(qh, "apply_reconciliation", apply_mock)
    monkeypatch.setattr(qh, "promote_victim_demographics", promote_mock)

    qh.handle_extraction_job(
        session,
        job,
        llm_client=MagicMock(),
        tier1_prompt_template="t1",
        tier2_prompt_template="t2",
        model_id="test-model",
    )

    promote_mock.assert_called_once_with(session, case_id=job.case_id)
    assert call_order == ["reconcile", "promote"]
