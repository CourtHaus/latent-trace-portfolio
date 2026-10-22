"""Correlation grading + churn harness — old vs new (rarity-weighted) formula.

Four subcommands share a single JSONL scan file so the expensive corpus pass
runs exactly once:

  scan   --out pairs.jsonl   one corpus pass; per (parent, candidate) pair,
                             compute BOTH formulas and dump a JSON line.
  churn  --scan pairs.jsonl  OLD vs NEW lead-set volumes, overlap, gain/loss,
                             and the floor-vs-volume calibration curve (Task 8).
  sample --scan pairs.jsonl  deterministic stratified CSV for hand grading.
  report --scan pairs.jsonl --grades graded.csv   p/x means + concordance.

READ-ONLY. The harness issues only SELECTs (reuses the candidate-pool SQL from
service.py and the base-rate queries from base_rates.py); it never opens a
write transaction. Run against the LOCAL live ``casesignal`` DB.

The OLD formula is FROZEN here (it was deleted from prod in the Phase-A
rewrite). It is reconstructed verbatim from git ``cb69c00`` — flat weights
(weapon 1.0, location_type 1.0, gender/race/age_band 0.5), demographics matched
on RAW values, the ``unknown == unknown`` demographic quirk PRESERVED for
fidelity, decade age bands, floor 1.5, no min-dimensions rule. The NEW formula
is imported wholesale from ``casesignal.correlation`` — never reimplemented.

Run:
  set -a; source .env; set +a
  python -m tools.correlation_grading scan --out /tmp/pairs.jsonl
  python -m tools.correlation_grading churn  --scan /tmp/pairs.jsonl
  python -m tools.correlation_grading sample --scan /tmp/pairs.jsonl --out /tmp/grading.csv --n 100
  python -m tools.correlation_grading report --scan /tmp/pairs.jsonl --grades /tmp/grading.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _ensure_src_on_path() -> None:
    src = Path(__file__).resolve().parent.parent / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_src_on_path()

# OLD-formula frozen constants (git cb69c00:correlation/config.py).
_OLD_WEIGHT_WEAPON = 1.0
_OLD_WEIGHT_LOCATION_TYPE = 1.0
_OLD_WEIGHT_VICTIM_GENDER = 0.5
_OLD_WEIGHT_VICTIM_RACE = 0.5
_OLD_WEIGHT_VICTIM_AGE_BAND = 0.5
_OLD_AGE_BAND_YEARS = 10
_OLD_SCORE_FLOOR = 1.5

_BASE_URL = "https://latenttrace.org/cold-cases"


# --------------------------------------------------------------------------
# OLD formula (frozen). Reconstructed from git cb69c00.
# --------------------------------------------------------------------------
def _old_format_age_band(age_num: int | None) -> str | None:
    """Decade band: lower=(age//10)*10, upper=lower+9. None for None/negative.

    Verbatim from cb69c00:correlation/scoring.py::format_age_band.
    """
    if age_num is None or age_num < 0:
        return None
    lower = (age_num // _OLD_AGE_BAND_YEARS) * _OLD_AGE_BAND_YEARS
    upper = lower + (_OLD_AGE_BAND_YEARS - 1)
    return f"{lower}-{upper}"


def _old_mo_match(
    parent_val: str | None, cand_val: str | None, name: str, weight: float
) -> tuple[float, str | None]:
    """MO dimension (weapon/location_type): both concrete (non-None,
    non-'unknown') AND equal. Verbatim from cb69c00 _build_match."""
    if (
        parent_val is None
        or parent_val == "unknown"
        or cand_val is None
        or cand_val == "unknown"
    ):
        return 0.0, None
    if parent_val != cand_val:
        return 0.0, None
    return weight, name


def _old_demographic_match(
    parent_val: str | None, cand_val: str | None, name: str, weight: float
) -> tuple[float, str | None]:
    """Demographic dimension: matches on RAW equal values. Verbatim from
    cb69c00 _build_demographic_match — this INCLUDES the 'unknown'=='unknown'
    quirk (only None is excluded), preserved for churn fidelity."""
    if parent_val is None or cand_val is None:
        return 0.0, None
    if parent_val != cand_val:
        return 0.0, None
    return weight, name


def _old_score_pair(row: dict[str, Any]) -> tuple[float, list[str]]:
    """Flat-weight OLD score + matched dimension names for one candidate row.

    Row keys mirror the candidate-pool SQL: p_weapon/weapon,
    p_location_type/location_type, p_gender/gender, p_race/race,
    p_age_num/age_num. Demographics use RAW values (no canonicalization).
    """
    score = 0.0
    dims: list[str] = []

    for s, d in (
        _old_mo_match(row["p_weapon"], row["weapon"], "weapon", _OLD_WEIGHT_WEAPON),
        _old_mo_match(
            row["p_location_type"],
            row["location_type"],
            "location_type",
            _OLD_WEIGHT_LOCATION_TYPE,
        ),
        _old_demographic_match(
            row["p_gender"], row["gender"], "victim_gender", _OLD_WEIGHT_VICTIM_GENDER
        ),
        _old_demographic_match(
            row["p_race"], row["race"], "victim_race", _OLD_WEIGHT_VICTIM_RACE
        ),
        _old_demographic_match(
            _old_format_age_band(row["p_age_num"]),
            _old_format_age_band(row["age_num"]),
            "victim_age_band",
            _OLD_WEIGHT_VICTIM_AGE_BAND,
        ),
    ):
        score += s
        if d is not None:
            dims.append(d)

    return score, dims


# --------------------------------------------------------------------------
# Pure helpers (DB-free; unit-tested in tests/unit/test_correlation_grading.py).
# --------------------------------------------------------------------------
def concordance(p_scores: list[float], x_scores: list[float]) -> float:
    """Probability a random (plausible, implausible) pair is correctly ordered
    by score: fraction of cross pairs with p_score > x_score, ties count 0.5
    (Mann-Whitney U / AUC). Returns 0.5 when either side is empty (no
    information either way)."""
    if not p_scores or not x_scores:
        return 0.5
    wins = 0.0
    for p in p_scores:
        for x in x_scores:
            if p > x:
                wins += 1.0
            elif p == x:
                wins += 0.5
    return wins / (len(p_scores) * len(x_scores))


def _new_is_lead(pair: dict[str, Any], floor: float) -> bool:
    """NEW lead rule: new_score >= floor AND >= MIN_DIMENSIONS matched dims."""
    from casesignal.correlation.config import CORRELATION_MIN_DIMENSIONS

    return (
        float(pair["new_score"]) >= floor
        and len(pair["new_dims"]) >= CORRELATION_MIN_DIMENSIONS
    )


def _old_is_lead(pair: dict[str, Any]) -> bool:
    """OLD lead rule: old_score >= 1.5, no min-dimensions rule."""
    return float(pair["old_score"]) >= _OLD_SCORE_FLOOR


def _cap_top_n(
    pairs: list[dict[str, Any]], score_key: str
) -> list[dict[str, Any]]:
    """Per-parent top-CORRELATION_TOP_N by score DESC, distance ASC."""
    from casesignal.correlation.config import CORRELATION_TOP_N

    by_parent: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for p in pairs:
        by_parent[p["parent_id"]].append(p)
    kept: list[dict[str, Any]] = []
    for group in by_parent.values():
        group.sort(key=lambda p: (-float(p[score_key]), float(p["distance_miles"])))
        kept.extend(group[:CORRELATION_TOP_N])
    return kept


def lead_volume_curve(
    pairs: list[dict[str, Any]], floors: list[float]
) -> list[tuple[float, int]]:
    """NEW (parent, lead) pair count per floor, with the min-dimensions rule
    and per-parent top-N cap applied. Monotonically non-increasing in floor.

    Each pair dict needs: parent_id, distance_miles, new_score, new_dims
    (a list; its length is the matched-dimension count).
    """
    out: list[tuple[float, int]] = []
    for floor in floors:
        leads = [p for p in pairs if _new_is_lead(p, floor)]
        out.append((floor, len(_cap_top_n(leads, "new_score"))))
    return out


def stratify(pairs: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Deterministic stratified sample of ~n pairs for hand grading. No RNG:
    each stratum is sorted by a stable key and decimated take-every-kth so
    re-runs reproduce byte-for-byte.

    Strata (target counts when available): ~30% old-only leads, ~30% new-only
    leads, ~20% both, ~20% non-leads spread across new_score quartiles. Pairs
    are de-duplicated across strata in that priority order.

    Each pair dict needs: parent_id, cand_id, old_score, new_score, new_dims,
    distance_miles.
    """

    def take_evenly(items: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        if k <= 0 or not items:
            return []
        if len(items) <= k:
            return list(items)
        step = len(items) / k  # float stride for an even spread, no RNG
        return [items[int(i * step)] for i in range(k)]

    def key(p: dict[str, Any]) -> tuple[Any, ...]:
        return (p["parent_id"], p["cand_id"])

    old_leads = {key(p): p for p in pairs if _old_is_lead(p)}
    new_leads = {key(p): p for p in pairs if _new_is_lead(p, _floor())}

    old_only = sorted(
        (p for k, p in old_leads.items() if k not in new_leads), key=key
    )
    new_only = sorted(
        (p for k, p in new_leads.items() if k not in old_leads), key=key
    )
    both = sorted((p for k, p in old_leads.items() if k in new_leads), key=key)

    lead_keys = set(old_leads) | set(new_leads)
    non_leads = sorted(
        (p for p in pairs if key(p) not in lead_keys),
        key=lambda p: (float(p["new_score"]), key(p)),
    )

    want_old = max(1, round(n * 0.30))
    want_new = max(1, round(n * 0.30))
    want_both = max(1, round(n * 0.20))
    want_non = max(1, n - want_old - want_new - want_both)

    selected: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def add(items: list[dict[str, Any]]) -> None:
        for p in items:
            kp = key(p)
            if kp not in seen:
                seen.add(kp)
                selected.append(p)

    add(take_evenly(old_only, want_old))
    add(take_evenly(new_only, want_new))
    add(take_evenly(both, want_both))

    # Non-leads spread across new_score quartiles (split the sorted list into
    # 4 contiguous blocks, decimate each evenly).
    if non_leads:
        per_q = max(1, want_non // 4)
        q = max(1, len(non_leads) // 4)
        quartiles = [non_leads[i * q : (i + 1) * q] for i in range(3)]
        quartiles.append(non_leads[3 * q :])
        for block in quartiles:
            add(take_evenly(block, per_q))

    return selected


def _floor() -> float:
    from casesignal.correlation.config import CORRELATION_SCORE_FLOOR

    return float(CORRELATION_SCORE_FLOOR)


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------
_SCAN_PARENTS_SQL = """
    SELECT c.case_id
      FROM cold_case.cases c
      JOIN etl.dataset_version dv
            ON dv.dataset_version_id = c.dataset_version_id
           AND dv.ingestion_status = 'published'
     WHERE c.geom IS NOT NULL
       AND c.incident_date IS NOT NULL
     ORDER BY c.case_id
"""


def _scan(out_path: Path) -> int:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from casesignal.correlation.base_rates import get_base_rates
    from casesignal.correlation.config import (
        CORRELATION_GEO_MILES,
        CORRELATION_TIME_YEARS,
    )
    from casesignal.correlation.scoring import (
        DimensionValues,
        normalized_score,
        score_pair,
    )
    from casesignal.correlation.service import _QUERY

    miles_to_meters = 1609.344
    geo_meters = CORRELATION_GEO_MILES * miles_to_meters
    bbox_deg = geo_meters / 69_000.0

    engine = create_engine(os.environ["DATABASE_URL"])
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        rates = get_base_rates(session)
        parent_ids = [r[0] for r in session.execute(text(_SCAN_PARENTS_SQL))]
        print(f"scan: {len(parent_ids)} published parent cases", file=sys.stderr)

        n_pairs = 0
        with out_path.open("w", encoding="utf-8") as fh:
            for i, parent_id in enumerate(parent_ids, start=1):
                rows = (
                    session.execute(
                        _QUERY,
                        {
                            "case_id": parent_id,
                            "geo_meters": geo_meters,
                            "bbox_deg": bbox_deg,
                            "time_years": CORRELATION_TIME_YEARS,
                        },
                    )
                    .mappings()
                    .all()
                )
                for r in rows:
                    row = dict(r)
                    old_score, old_dims = _old_score_pair(row)

                    parent = DimensionValues(
                        weapon=row["p_weapon"],
                        weapon_low_confidence=row["p_weapon_low_confidence"],
                        location_type=row["p_location_type"],
                        location_type_low_confidence=row["p_location_type_low_confidence"],
                        gender=row["p_gender"],
                        race=row["p_race"],
                        age=row["p_age_num"],
                    )
                    cand = DimensionValues(
                        weapon=row["weapon"],
                        weapon_low_confidence=row["weapon_low_confidence"],
                        location_type=row["location_type"],
                        location_type_low_confidence=row["location_type_low_confidence"],
                        gender=row["gender"],
                        race=row["race"],
                        age=row["age_num"],
                    )
                    raw_bits, dims = score_pair(parent, cand, rates)
                    distance = float(row["distance_miles"])
                    years_apart = int(row["years_apart"])
                    new_score, prox = normalized_score(
                        raw_bits, distance, years_apart, rates
                    )

                    fh.write(
                        json.dumps(
                            {
                                "parent_id": parent_id,
                                "cand_id": row["case_id"],
                                "parent_slug": None,  # parent slug not in row
                                "cand_slug": row["slug"],
                                "distance_miles": distance,
                                "years_apart": years_apart,
                                "old_score": old_score,
                                "old_dims": old_dims,
                                "new_score": new_score,
                                "new_dims": [d.name for d in dims],
                                "new_raw_bits": raw_bits,
                                "proximity_factor": prox,
                            }
                        )
                        + "\n"
                    )
                    n_pairs += 1

                if i % 500 == 0:
                    print(
                        f"scan: {i}/{len(parent_ids)} parents, {n_pairs} pairs",
                        file=sys.stderr,
                    )

        print(
            f"scan: done — {n_pairs} pairs from {len(parent_ids)} parents -> {out_path}",
            file=sys.stderr,
        )
    finally:
        session.close()
        engine.dispose()
    return 0


# Parent slug backfill: the candidate-pool SQL exposes only candidate slugs.
# scan leaves parent_slug=None; we resolve it once here from the scan set so
# sample's URLs are correct, with a single read-only query.
def _parent_slugs(parent_ids: set[int]) -> dict[int, str]:
    if not parent_ids:
        return {}
    from sqlalchemy import bindparam, create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(os.environ["DATABASE_URL"])
    session = sessionmaker(bind=engine)()
    try:
        stmt = text(
            "SELECT case_id, slug FROM cold_case.cases WHERE case_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        rows = session.execute(stmt, {"ids": sorted(parent_ids)}).all()
        return {cid: slug for cid, slug in rows}
    finally:
        session.close()
        engine.dispose()


# --------------------------------------------------------------------------
# scan-file IO
# --------------------------------------------------------------------------
def _load_scan(scan_path: Path) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    with scan_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))
    return pairs


# --------------------------------------------------------------------------
# churn
# --------------------------------------------------------------------------
def _lead_keyset(pairs: list[dict[str, Any]], *, old: bool) -> set[tuple[Any, Any]]:
    """The (parent, lead) pair-set under OLD or NEW rules (top-N capped)."""
    if old:
        qualifying = [p for p in pairs if _old_is_lead(p)]
        capped = _cap_top_n(qualifying, "old_score")
    else:
        qualifying = [p for p in pairs if _new_is_lead(p, _floor())]
        capped = _cap_top_n(qualifying, "new_score")
    return {(p["parent_id"], p["cand_id"]) for p in capped}


def _churn(scan_path: Path) -> int:
    pairs = _load_scan(scan_path)
    old_set = _lead_keyset(pairs, old=True)
    new_set = _lead_keyset(pairs, old=False)

    old_by_parent: dict[Any, set[Any]] = defaultdict(set)
    new_by_parent: dict[Any, set[Any]] = defaultdict(set)
    for p_id, c_id in old_set:
        old_by_parent[p_id].add(c_id)
    for p_id, c_id in new_set:
        new_by_parent[p_id].add(c_id)

    inter = old_set & new_set
    union = old_set | new_set
    jaccard = (len(inter) / len(union) * 100.0) if union else 0.0

    parents = set(old_by_parent) | set(new_by_parent)
    gained_all_new = sum(
        1
        for p in parents
        if not old_by_parent.get(p) and new_by_parent.get(p)
    )
    lost_all = sum(
        1
        for p in parents
        if old_by_parent.get(p) and not new_by_parent.get(p)
    )

    print("== CHURN: OLD vs NEW correlation formula ==")
    print(f"total pairs scanned:                 {len(pairs)}")
    print(f"OLD (parent, lead) pairs:            {len(old_set)}")
    print(f"NEW (parent, lead) pairs:            {len(new_set)}")
    print(f"overlap (both):                      {len(inter)}")
    print(f"Jaccard overlap of lead pair-sets:   {jaccard:.1f}%")
    print(f"parents gaining all-new leads:       {gained_all_new}")
    print(f"parents losing all leads:            {lost_all}")
    print(f"NEW score floor (config):            {_floor()}")
    print()
    print("== FLOOR vs NEW (parent, lead) VOLUME (min-dims + top-N applied) ==")
    floors = [round(0.25 * i, 2) for i in range(1, 21)]  # 0.25 .. 5.0
    for floor, count in lead_volume_curve(pairs, floors):
        print(f"  floor {floor:>4.2f}  ->  {count} lead pairs")
    return 0


# --------------------------------------------------------------------------
# sample
# --------------------------------------------------------------------------
_GRADE_LEGEND = (
    "grade legend: p = plausible correlation, x = implausible. "
    "Leave blank to skip. Fill the 'grade' column, then run `report`."
)


def _url(case_id: Any, slug: Any) -> str:
    return f"{_BASE_URL}/{case_id}/{slug}"


def _sample(scan_path: Path, out_path: Path, n: int) -> int:
    pairs = _load_scan(scan_path)
    chosen = stratify(pairs, n)

    # Backfill parent slugs (scan stored None) so parent URLs are correct.
    slug_map = _parent_slugs({int(p["parent_id"]) for p in chosen})

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "parent_url",
                "candidate_url",
                "old_score",
                "old_dims",
                "new_score",
                "new_dims",
                "proximity_factor",
                "distance_miles",
                "years_apart",
                "grade",
            ]
        )
        for p in chosen:
            parent_slug = slug_map.get(int(p["parent_id"]), p.get("parent_slug") or "")
            writer.writerow(
                [
                    _url(p["parent_id"], parent_slug),
                    _url(p["cand_id"], p["cand_slug"]),
                    f"{float(p['old_score']):.3f}",
                    "|".join(p["old_dims"]),
                    f"{float(p['new_score']):.3f}",
                    "|".join(p["new_dims"]),
                    f"{float(p['proximity_factor']):.3f}",
                    f"{float(p['distance_miles']):.2f}",
                    p["years_apart"],
                    "",
                ]
            )

    print(f"sample: {len(chosen)} rows -> {out_path}", file=sys.stderr)
    print(_GRADE_LEGEND, file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def _report(scan_path: Path, grades_path: Path) -> int:
    graded: list[dict[str, str]] = []
    with grades_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            grade = (row.get("grade") or "").strip().lower()
            if grade in ("p", "x"):
                graded.append(row)

    if not graded:
        print("report: no rows graded p/x yet — fill the grade column.")
        return 1

    def scores(formula: str, grade: str) -> list[float]:
        return [
            float(r[formula])
            for r in graded
            if (r.get("grade") or "").strip().lower() == grade
        ]

    print("== GRADING REPORT (p = plausible, x = implausible) ==")
    print(f"graded rows: {len(graded)}  "
          f"(p={sum(1 for r in graded if r['grade'].strip().lower() == 'p')}, "
          f"x={sum(1 for r in graded if r['grade'].strip().lower() == 'x')})")
    print()
    print(f"{'formula':<10}{'mean(p)':>10}{'mean(x)':>10}{'concordance':>14}")
    for label, col in (("OLD", "old_score"), ("NEW", "new_score")):
        p_s = scores(col, "p")
        x_s = scores(col, "x")
        mean_p = sum(p_s) / len(p_s) if p_s else float("nan")
        mean_x = sum(x_s) / len(x_s) if x_s else float("nan")
        print(f"{label:<10}{mean_p:>10.3f}{mean_x:>10.3f}{concordance(p_s, x_s):>14.3f}")

    print()
    print("(concordance = P(a random plausible pair outscores a random "
          "implausible one); 0.5 = no separation, 1.0 = perfect.)")
    print()
    _churn(scan_path)
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Correlation grading + churn harness (old vs new formula). READ-ONLY."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="one corpus pass -> pairs JSONL")
    p_scan.add_argument("--out", required=True, type=Path)

    p_churn = sub.add_parser("churn", help="OLD vs NEW lead volume + floor curve")
    p_churn.add_argument("--scan", required=True, type=Path)

    p_sample = sub.add_parser("sample", help="deterministic stratified grading CSV")
    p_sample.add_argument("--scan", required=True, type=Path)
    p_sample.add_argument("--out", required=True, type=Path)
    p_sample.add_argument("--n", type=int, default=100)

    p_report = sub.add_parser("report", help="p/x means + concordance from graded CSV")
    p_report.add_argument("--scan", required=True, type=Path)
    p_report.add_argument("--grades", required=True, type=Path)

    args = parser.parse_args(argv)

    if args.cmd == "scan":
        return _scan(args.out)
    if args.cmd == "churn":
        return _churn(args.scan)
    if args.cmd == "sample":
        return _sample(args.scan, args.out, args.n)
    if args.cmd == "report":
        return _report(args.scan, args.grades)
    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
