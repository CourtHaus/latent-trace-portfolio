"""Orchestration for the discover and finalize phases (thin, injectable seams)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from casesignal.scout.classify import apply_verdict, verdict_from_json
from casesignal.scout.discovery.catalog import (
    fetch_arcgis,
    fetch_socrata,
    parse_arcgis,
    parse_socrata,
)
from casesignal.scout.discovery.ingest_results import candidates_from_results
from casesignal.scout.discovery.templating import queries_for_state
from casesignal.scout.dossier import render_dossier
from casesignal.scout.estimate import estimate_count_from_listing, estimate_plottability
from casesignal.scout.frontier import state_frontier
from casesignal.scout.models import Candidate, Confidence, GateResult, Status
from casesignal.scout.registry import Registry, covered_states
from casesignal.scout.score import score_candidate

# 50 two-letter USPS state codes.
ALL_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

SearchFn = Callable[[list[str]], list[dict[str, Any]]]


def candidate_slug(cid: str) -> str:
    """Filesystem-safe token for a candidate id.

    Web candidate ids are host+path (e.g. ``dps.texas.gov/apps``) and contain a
    ``/``, so they cannot be used directly as flat file or directory names.
    Catalog ids are dataset slugs with no separator and pass through unchanged.
    Both the evidence dir and the ``<slug>.json`` verdict file use this mapping,
    so the classification workflow that drops verdicts must slug the id too.
    """
    return cid.replace("/", "__")


@dataclass
class Scope:
    tier: str | None = None
    state: str | None = None
    counties: bool = False
    max_candidates: int = 50


def discover(
    scope: Scope,
    registry_path: Path,
    sources_dir: Path,
    out_dir: Path,
    search_fn: SearchFn,
    catalog_client: Any = None,
) -> Path:
    reg = Registry.load(registry_path)
    seen = {c.id for c in reg.all()}
    new_candidates: list[Candidate] = []

    if scope.tier == "state":
        targets = state_frontier(covered_states(sources_dir), ALL_STATES)
        queries: list[str] = []
        for t in targets:
            queries.extend(queries_for_state(t))
        results = search_fn(queries)
        new_candidates.extend(candidates_from_results(results, seen))
    elif scope.counties or scope.state is not None:
        # County-tier discovery is a later sub-project (Tier B). Make the no-op
        # explicit AND generate nothing: return an empty worklist before the
        # catalog channel runs, so "no candidates generated" is actually true
        # (the CLI always supplies a catalog client, which would otherwise run
        # global discovery and contradict this message).
        print(
            "scout: county-tier discovery not yet implemented (Tier B); "
            "no candidates generated"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        worklist = out_dir / "worklist.jsonl"
        worklist.write_text("")
        return worklist

    if catalog_client is not None:
        for q in ("cold case homicide", "unsolved homicide"):
            new_candidates.extend(parse_socrata(fetch_socrata(catalog_client, q), seen))
            new_candidates.extend(parse_arcgis(fetch_arcgis(catalog_client, q), seen))

    dropped = 0
    if len(new_candidates) > scope.max_candidates:
        dropped = len(new_candidates) - scope.max_candidates
        new_candidates = new_candidates[: scope.max_candidates]

    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = out_dir / "evidence"
    worklist = out_dir / "worklist.jsonl"
    with worklist.open("w") as fh:
        for c in new_candidates:
            c.evidence_dir = str(evidence_root / candidate_slug(c.id))
            reg.upsert(c)
            fh.write(
                json.dumps(
                    {
                        "id": c.id,
                        "index_url": c.index_url,
                        "evidence_dir": c.evidence_dir,
                        "verdict_filename": f"{candidate_slug(c.id)}.json",
                    }
                )
                + "\n"
            )
    reg.save(registry_path)
    if dropped:
        print(f"scout: capped at {scope.max_candidates}; deferred {dropped} candidates")
    return worklist


def finalize(registry_path: Path, verdicts_dir: Path, run_date: str, out_dir: Path) -> Path:
    reg = Registry.load(registry_path)
    for c in reg.all():
        if c.status not in (Status.CANDIDATE, Status.REJECTED, Status.NEEDS_REVIEW):
            continue
        verdict_file = verdicts_dir / f"{candidate_slug(c.id)}.json"
        if not verdict_file.exists():
            if c.status == Status.CANDIDATE:
                c.status = Status.NEEDS_REVIEW
                reg.upsert(c)
            continue
        apply_verdict(c, verdict_from_json(json.loads(verdict_file.read_text())))
        # A re-applied verdict that now PASSES both gates must clear a stale
        # REJECTED/NEEDS_REVIEW label so it is scored and labeled correctly.
        # apply_verdict only ever SETS reject on gate-fail; it never clears it.
        if (
            c.gates is not None
            and c.gates.cold_homicide == GateResult.PASS
            and c.gates.official_first_party == GateResult.PASS
        ):
            c.status = Status.CANDIDATE
        if c.status == Status.REJECTED:
            reg.upsert(c)
            continue
        # Estimate count from a listing evidence file if present. Only a genuine
        # catalog/API count (Confidence.EXACT) is preserved as api_count; a prior
        # VISIBLE/PROBED estimate must be re-derived from the listing, never fed
        # back as if it were exact (which would promote it to EXACT and drop the
        # score damping on every re-finalize).
        if c.evidence_dir:
            listing = Path(c.evidence_dir) / "listing.html"
            if listing.exists():
                api_count = (
                    c.case_count.value
                    if c.case_count and c.case_count.confidence == Confidence.EXACT
                    else None
                )
                c.case_count = estimate_count_from_listing(
                    listing.read_text(), api_count=api_count
                )
        if c.plottability is None:
            c.plottability, c.plottability_basis = estimate_plottability(c.fields)
        c.score, c.score_breakdown = score_candidate(c)
        reg.upsert(c)

    reg.save(registry_path)
    dossier = out_dir / f"dossier-{run_date}.md"
    dossier.write_text(render_dossier(reg, run_date))
    return dossier
