"""CLI: casesignal-extract-cold-cases

Bulk extractor trigger. Reads rows that lack an extraction at the current
(prompt_hash, model_id, tier), calls extract_case() / extract_case_tier2()
with semaphore-bounded concurrency, writes results transactionally.

`--tier 1|2|both` selects which tier(s) to run. Default `both` runs Tier-1
followed by Tier-2 for each case (so the cost estimate is doubled when
both tiers are enabled). Tier-2 also runs the canonical-value backfill
(populates cold_case.cases.incident_date / address when NULL), persists the
per-victim roster to cold_case.victim_extraction, reconciles victim rows
(splitting collapsed multi-victim rows, recovering dropped victims), promotes
per-victim age/gender onto NULL cold_case.victim columns (Phase 2,
fill-NULL-only; see promote_demographics), and enqueues a geocoding_job per
case that produced an address.

Cost guardrail: prints estimated spend; if spend > $5 and --yes not set,
prompts for confirmation.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from casesignal.extraction.cold_case.extract_case import extract_case
from casesignal.extraction.cold_case.persistence import (
    CaseNeedingExtraction,
    backfill_canonical_values_from_tier2,
    enqueue_geocoding_job_from_tier2,
    extraction_exists_for,
    find_cases_needing_extraction,
    insert_extraction,
    insert_tier2_extraction,
    insert_victim_extractions,
)
from casesignal.extraction.cold_case.promote_demographics import (
    promote_victim_demographics,
)
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    get_pinned_model_id,
    load_tier1_prompt_template,
    load_tier2_v4_prompt_template,
)
from casesignal.extraction.cold_case.reconcile_victims import (
    apply_reconciliation,
    plan_reconciliation,
)
from casesignal.extraction.cold_case.tier2_extract_case import extract_case_tier2
from casesignal.extraction.cold_case.tier_policy import tier2_enabled_for_state
from casesignal.worker.llm.factory import make_llm_client

PRICE_PER_CALL_USD = 0.001  # gpt-4o-mini-2024-07-18, ~$0.001/call at current prompt length.
# Zero for local models (Ollama/Qwen) — the cost guardrail
# harmlessly skips prompting when estimate is below threshold.
COST_CONFIRMATION_THRESHOLD_USD = 5.0


def estimate_cost(row_count: int, tiers: list[int]) -> float:
    return row_count * len(tiers) * PRICE_PER_CALL_USD


def parse_case_ids_file_content(content: str) -> list[int]:
    """Parse a --case-ids-file body into an ordered, de-duplicated id list.

    One case_id per line. Blank lines and ``#`` comments (whole-line or inline
    trailing) are ignored. Order of first appearance is preserved so the
    re-extraction work set is deterministic.
    """
    ids: list[int] = []
    seen: set[int] = set()
    for line in content.splitlines():
        token = line.split("#", 1)[0].strip()
        if not token:
            continue
        case_id = int(token)
        if case_id not in seen:
            seen.add(case_id)
            ids.append(case_id)
    return ids


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="casesignal-extract-cold-cases",
        description="Extract MO fields (Tier-1) and/or Tier-2 fields from"
        " cold-case about_text via LLM.",
    )
    parser.add_argument(
        "--dataset-version",
        type=int,
        default=None,
        help="Limit to cases in a specific dataset_version_id",
    )
    parser.add_argument(
        "--case-id", type=int, default=None, help="Extract a single case by ID (for debugging)"
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Limit to cases in a specific state (e.g. TN, MD, OH). Combine with"
        " --tier 2 to backfill one state at a time.",
    )
    parser.add_argument(
        "--tier",
        choices=["1", "2", "both"],
        default="both",
        help="Which extraction tier(s) to run (default: both)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=5, help="Max parallel LLM calls (default 5)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run extractions, print results, DON'T write to DB"
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip cost-guardrail prompt above threshold"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract cases even if a matching (prompt_hash,"
        " model_id, prompt_tier) row already exists",
    )
    parser.add_argument(
        "--case-ids-file",
        type=str,
        default=None,
        help="Re-extract exactly the case_ids listed in this file (one per line,"
        " blank lines / # comments ignored), with force semantics for the"
        " selected tier(s). For targeted re-extraction after a prompt change.",
    )
    return parser.parse_args(argv)


def _tiers_from_arg(arg: str) -> list[int]:
    if arg == "1":
        return [1]
    if arg == "2":
        return [2]
    return [1, 2]


def _enabled_tiers_for_state(state: str | None, tiers: list[int]) -> list[int]:
    if tier2_enabled_for_state(state):
        return tiers
    return [tier for tier in tiers if tier != 2]


def _confirm_cost(row_count: int, tiers: list[int], auto_yes: bool) -> bool:
    cost = estimate_cost(row_count, tiers)
    total_calls = row_count * len(tiers)
    print(
        f"Estimated spend: {row_count} cases × {len(tiers)} tier(s) ="
        f" {total_calls} calls × ${PRICE_PER_CALL_USD:.4f} = ${cost:.2f}"
    )
    if cost <= COST_CONFIRMATION_THRESHOLD_USD or auto_yes:
        return True
    answer = input(f"This will spend ~${cost:.2f}. Continue? [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    tiers = _tiers_from_arg(args.tier)
    case_ids: list[int] | None = None
    if args.case_ids_file is not None:
        with open(args.case_ids_file, encoding="utf-8") as fh:
            case_ids = parse_case_ids_file_content(fh.read())
        print(f"--case-ids-file: {len(case_ids)} case_ids to force-re-extract.")
    tier1_template = load_tier1_prompt_template()
    tier2_template = load_tier2_v4_prompt_template()
    tier1_hash = compute_prompt_hash(tier1_template)
    tier2_hash = compute_prompt_hash(tier2_template)
    pinned_model = get_pinned_model_id()
    llm_client = make_llm_client(model_id=pinned_model)

    engine = create_engine(os.environ["DATABASE_URL"])
    Session = sessionmaker(engine)

    needed_tiers_by_case: dict[int, set[int]] = {}
    with Session() as session:
        if args.case_id is not None:
            rows = session.execute(
                text("SELECT case_id, about_text, state FROM cold_case.cases WHERE case_id = :cid"),
                {"cid": args.case_id},
            ).all()
            cases = [
                CaseNeedingExtraction(case_id=r.case_id, about_text=r.about_text) for r in rows
            ]
            state_by_case = {r.case_id: r.state for r in rows}
            for case in cases:
                needed_tiers_by_case[case.case_id] = set()
                for tier in _enabled_tiers_for_state(state_by_case.get(case.case_id), tiers):
                    prompt_hash = tier1_hash if tier == 1 else tier2_hash
                    if args.force or not extraction_exists_for(
                        session, case.case_id, prompt_hash, pinned_model, tier
                    ):
                        needed_tiers_by_case[case.case_id].add(tier)
        elif case_ids is not None:
            # Targeted re-extraction: the work set is EXACTLY the listed ids
            # (force semantics — re-extract regardless of any existing row, and
            # independent of the current prompt_hash so a hash change does not
            # pull in the rest of the corpus). Intersected with the enabled
            # tier(s) per state.
            rows = session.execute(
                text(
                    "SELECT case_id, about_text, state FROM cold_case.cases"
                    " WHERE about_text IS NOT NULL AND about_text != ''"
                    " AND case_id = ANY(:ids)"
                ),
                {"ids": case_ids},
            ).all()
            found = {r.case_id for r in rows}
            missing = [cid for cid in case_ids if cid not in found]
            if missing:
                print(
                    f"  warning: {len(missing)} requested case_id(s) not found or"
                    f" have empty about_text, skipped: {missing}",
                    file=sys.stderr,
                )
            case_by_id: dict[int, CaseNeedingExtraction] = {}
            for r in rows:
                case_by_id[r.case_id] = CaseNeedingExtraction(
                    case_id=r.case_id, about_text=r.about_text
                )
                needed_tiers_by_case[r.case_id] = set(_enabled_tiers_for_state(r.state, tiers))
            cases = [case_by_id[cid] for cid in sorted(case_by_id)]
        else:
            case_by_id = {}
            if args.force:
                sql = """
                    SELECT case_id, about_text, state
                      FROM cold_case.cases
                     WHERE about_text IS NOT NULL AND about_text != ''
                """
                params: dict[str, object] = {}
                if args.dataset_version is not None:
                    sql += "\n                       AND dataset_version_id = :dv"
                    params["dv"] = args.dataset_version
                if args.state is not None:
                    sql += "\n                       AND state = :state"
                    params["state"] = args.state
                rows = session.execute(text(sql), params).all()
                for r in rows:
                    case = CaseNeedingExtraction(case_id=r.case_id, about_text=r.about_text)
                    case_by_id[case.case_id] = case
                    needed_tiers_by_case[case.case_id] = set(
                        _enabled_tiers_for_state(r.state, tiers)
                    )
            else:
                for tier in tiers:
                    prompt_hash = tier1_hash if tier == 1 else tier2_hash
                    tier_cases = find_cases_needing_extraction(
                        session,
                        prompt_hash=prompt_hash,
                        model_id=pinned_model,
                        prompt_tier=tier,
                        dataset_version_id=args.dataset_version,
                        state=args.state,
                    )
                    for case in tier_cases:
                        case_by_id[case.case_id] = case
                        needed_tiers_by_case.setdefault(case.case_id, set()).add(tier)
            cases = [case_by_id[cid] for cid in sorted(case_by_id)]

    cases = [case for case in cases if needed_tiers_by_case.get(case.case_id)]

    row_count = len(cases)
    if row_count == 0:
        print("No cases need extraction at current (prompt_hash, model_id). Done.")
        engine.dispose()
        return 0

    if not _confirm_cost(row_count, tiers, auto_yes=args.yes):
        print("Aborted.")
        engine.dispose()
        return 1

    successful = 0
    failed = 0
    low_confidence_weapon = 0
    low_confidence_location = 0
    tier2_address_count = 0

    def _process_case(c: CaseNeedingExtraction) -> dict[str, Any]:
        out: dict[str, Any] = {"case_id": c.case_id}
        case_tiers = needed_tiers_by_case[c.case_id]
        if 1 in case_tiers:
            out["tier1"] = extract_case(
                case_id=c.case_id,
                about_text=c.about_text,
                llm_client=llm_client,
                prompt_template=tier1_template,
                model_id=pinned_model,
            )
        if 2 in case_tiers:
            out["tier2"] = extract_case_tier2(
                case_id=c.case_id,
                about_text=c.about_text,
                llm_client=llm_client,
                prompt_template=tier2_template,
                model_id=pinned_model,
            )
        return out

    # Fetch state + source_county_fips so the post-tier-2 geocoding-job
    # enqueue has the per-case context it needs.
    with Session() as session:
        case_meta = {
            r.case_id: (r.state, r.source_county_fips)
            for r in session.execute(
                text(
                    "SELECT case_id, state, source_county_fips"
                    " FROM cold_case.cases"
                    " WHERE case_id = ANY(:ids)"
                ),
                {"ids": [c.case_id for c in cases]},
            )
        }

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        future_to_case = {pool.submit(_process_case, c): c for c in cases}
        with Session() as session:
            for future in as_completed(future_to_case):
                case = future_to_case[future]
                try:
                    bundle = future.result()
                except Exception as exc:
                    # LLM/network errors (e.g. APITimeoutError after retries) MUST
                    # not crash the batch — re-extraction over thousands of cases
                    # is long-running and one stuck call shouldn't lose progress.
                    print(
                        f"  case_id={case.case_id}: extraction failed — {exc}",
                        file=sys.stderr,
                    )
                    failed += 1
                    continue
                cid = bundle["case_id"]
                # A malformed/unusable LLM response must NOT be persisted as a
                # successful row (it would be skipped forever by the idempotency
                # check). Drop it from the bundle so it stays re-runnable.
                for _tier in ("tier1", "tier2"):
                    if bundle.get(_tier) is not None and bundle[_tier].failed:
                        print(
                            f"  case_id={cid}: {_tier} extraction failed, not persisted"
                            f" — {bundle[_tier].notes}",
                            file=sys.stderr,
                        )
                        failed += 1
                        del bundle[_tier]
                if not args.dry_run:
                    try:
                        if "tier1" in bundle:
                            insert_extraction(session, bundle["tier1"])
                        if "tier2" in bundle:
                            ext = bundle["tier2"]
                            insert_tier2_extraction(session, ext)
                            backfill_canonical_values_from_tier2(session, ext)
                            state, county_fips = case_meta.get(cid, (None, None))
                            enqueue_geocoding_job_from_tier2(
                                session,
                                ext,
                                state_code=state,
                                county_fips=county_fips,
                            )
                            insert_victim_extractions(session, ext)
                            victim_rows = session.execute(
                                text(
                                    "SELECT victim_id, first_name, last_name"
                                    " FROM cold_case.victim"
                                    " WHERE case_id = :cid"
                                    " ORDER BY victim_id"
                                ),
                                {"cid": cid},
                            ).mappings().all()
                            existing = [dict(r) for r in victim_rows]
                            roster = [
                                {"ordinal": v.ordinal, "name": v.name.value}
                                for v in ext.victims
                            ]
                            plan = plan_reconciliation(existing, roster)
                            apply_reconciliation(
                                session, cid, plan,
                                model_id=ext.model_id,
                                prompt_hash=ext.prompt_hash,
                            )
                            promote_victim_demographics(session, case_id=cid)
                            if ext.address.value:
                                tier2_address_count += 1
                        session.commit()
                    except Exception as exc:
                        session.rollback()
                        print(f"  case_id={cid}: insert failed — {exc}", file=sys.stderr)
                        failed += 1
                        continue
                else:
                    # Dry-run: compute + print reconciliation plan without writing.
                    if "tier2" in bundle:
                        ext = bundle["tier2"]
                        victim_rows = session.execute(
                            text(
                                "SELECT victim_id, first_name, last_name"
                                " FROM cold_case.victim"
                                " WHERE case_id = :cid"
                                " ORDER BY victim_id"
                            ),
                            {"cid": cid},
                        ).mappings().all()
                        existing = [dict(r) for r in victim_rows]
                        roster = [
                            {"ordinal": v.ordinal, "name": v.name.value}
                            for v in ext.victims
                        ]
                        plan = plan_reconciliation(existing, roster)
                        print(
                            f"  [dry-run] case={cid}"
                            f" roster={[v.name.value for v in ext.victims]}"
                            f" plan: creates={[c['name'] for c in plan.creates]}"
                            f" deletes={plan.deletes}"
                            f" links={plan.links}"
                        )
                successful += 1
                if "tier1" in bundle:
                    if bundle["tier1"].weapon.low_confidence:
                        low_confidence_weapon += 1
                    if bundle["tier1"].location_type.low_confidence:
                        low_confidence_location += 1
                summary_bits = [f"case_id={cid}"]
                if "tier1" in bundle:
                    t1 = bundle["tier1"]
                    summary_bits.append(
                        f"weapon={t1.weapon.value} location_type={t1.location_type.value}"
                    )
                if "tier2" in bundle:
                    t2 = bundle["tier2"]
                    summary_bits.append(
                        f"date={t2.incident_date.value}"
                        f" age={t2.victim_age.value}"
                        f" gender={t2.victim_gender.value}"
                    )
                print("  " + " ".join(summary_bits))

    print()
    print(
        f"Summary: {successful} succeeded, {failed} failed."
        + (
            f" Tier-1 low-confidence: weapon={low_confidence_weapon},"
            f" location_type={low_confidence_location}."
            if 1 in tiers
            else ""
        )
        + (
            f" Tier-2: {tier2_address_count} addresses extracted (geocoding" f" jobs enqueued)."
            if 2 in tiers
            else ""
        )
    )
    engine.dispose()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
