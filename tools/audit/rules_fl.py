from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.etl.services.normalizers import clean_sentinel
from tools.audit.model import AuditContext, Finding, Layer, Rule, Severity, SourceAuditConfig
from tools.audit.predicates import (
    is_sentence_shaped,
    is_sentinel_address,
    name_would_reverse,
    narrative_has_address,
    text_has_date,
)

AGENCY_CLUSTER_MIN = 5

# Name tokens that mark an unidentified victim — never treat these as a real
# name for duplicate detection (R20).
_PLACEHOLDER_NAME_TOKENS = frozenset({"unknown", "unidentified"})


def _case_id_for(session: Session, ctx: AuditContext, source_case_id: str) -> int | None:
    return session.execute(
        text("SELECT case_id FROM cold_case.cases "
             "WHERE dataset_version_id=:dv AND source_case_id=:scid"),
        {"dv": ctx.dataset_version_id, "scid": source_case_id},
    ).scalar_one_or_none()


def _raw_rows(session: Session, ctx: AuditContext, cols: str) -> list[Any]:
    return list(session.execute(text(f"SELECT {cols} FROM {ctx.raw_table}")).all())


def r1_title_as_narrative(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, case_title, victim_name, narrative")
    hits = []
    for r in rows:
        if is_sentence_shaped(r.case_title) and not (r.narrative or "").strip():
            hits.append(r)
    case_ids, items = [], []
    for r in hits:
        cid = _case_id_for(session, ctx, r.source_case_id)
        if cid is None:
            continue
        case_ids.append(cid)
        last = (r.victim_name or "").split(",")[0].strip() or r.source_case_id
        items.append({"case_id": cid, "search": last,
                      "question": "Is FDLE's Narrative/Summary field genuinely blank?"})
    return Finding(len(hits), case_ids,
                   "narrative text trapped in case_title; narrative empty",
                   verify_items=items)


def r2_empty_narrative(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, narrative")
    hits = [r for r in rows if not (r.narrative or "").strip()]
    case_ids = [cid for r in hits if (cid := _case_id_for(session, ctx, r.source_case_id)) is not None]
    return Finding(len(hits), case_ids,
                   "raw narrative blank -> no Tier-1 extraction input")


def r3_sentinel_address(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, incident_address")
    hits = [r for r in rows if is_sentinel_address(r.incident_address)]
    case_ids = [cid for r in hits if (cid := _case_id_for(session, ctx, r.source_case_id)) is not None]
    return Finding(len(hits), case_ids,
                   "incident_address is a sentinel (comma/blank/punctuation)")


def r4_agency_cluster(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, incident_address")
    counts: dict[str, list[str]] = {}
    for r in rows:
        addr = (r.incident_address or "").strip()
        if not addr or is_sentinel_address(addr):
            continue
        counts.setdefault(addr, []).append(r.source_case_id)
    clustered = {a: scids for a, scids in counts.items() if len(scids) >= AGENCY_CLUSTER_MIN}
    case_ids, items = [], []
    biggest = sorted(clustered.items(), key=lambda kv: -len(kv[1]))
    for addr, scids in biggest:
        for scid in scids:
            cid = _case_id_for(session, ctx, scid)
            if cid is not None:
                case_ids.append(cid)
    for addr, scids in biggest[:3]:
        cid = _case_id_for(session, ctx, scids[0])
        if cid is not None:
            items.append({"case_id": cid, "search": addr,
                          "question": f"Does FDLE show an incident location distinct from "
                                      f"this agency address (shared by {len(scids)} cases)?"})
    detail = (f"{len(case_ids)} cases share {len(clustered)} addresses "
              f"(>= {AGENCY_CLUSTER_MIN} each) -> likely agency HQ, not incident location")
    return Finding(len(case_ids), case_ids, detail, verify_items=items)


def r5_name_no_comma(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, victim_name")
    hits = [r for r in rows if name_would_reverse(r.victim_name)]
    case_ids, items = [], []
    for r in hits:
        cid = _case_id_for(session, ctx, r.source_case_id)
        if cid is None:
            continue
        case_ids.append(cid)
        items.append({"case_id": cid, "search": r.victim_name,
                      "question": "Confirm first/last name order (no comma in source)."})
    return Finding(len(hits), case_ids,
                   "victim_name has no comma -> first/last likely reversed by split",
                   verify_items=items)


def r6_unnamed_victim(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, victim_name")
    hits = [r for r in rows
            if not (r.victim_name or "").strip()
            or (r.victim_name or "").strip().lower() == "unknown"]
    case_ids, items = [], []
    for r in hits:
        cid = _case_id_for(session, ctx, r.source_case_id)
        if cid is None:
            continue
        case_ids.append(cid)
        items.append({"case_id": cid, "search": r.source_case_id,
                      "question": "Does FDLE show a victim name (vs unidentified decedent)?"})
    return Finding(len(hits), case_ids,
                   "victim name blank/Unknown", verify_items=items)


def r7_dob_shape(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, dob")
    hits = []
    for r in rows:
        dob = (r.dob or "").strip()
        if not dob:
            continue
        parsed = None
        for fmt in ("%m-%d-%Y", "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(dob, fmt)
                break
            except ValueError:
                continue
        if parsed is None or parsed.year < 1900 or parsed.date() > date.today():
            hits.append(r)
    case_ids = [cid for r in hits if (cid := _case_id_for(session, ctx, r.source_case_id)) is not None]
    return Finding(len(hits), case_ids,
                   "dob present but unparseable or implausible")


def r8_missing_date(session: Session, ctx: AuditContext) -> Finding:
    rows = _raw_rows(session, ctx, "source_case_id, incident_date, narrative")
    hits = [r for r in rows if not (r.incident_date or "").strip()]
    recoverable = sum(1 for r in hits if text_has_date(r.narrative))
    case_ids = [cid for r in hits if (cid := _case_id_for(session, ctx, r.source_case_id)) is not None]
    detail = (f"incident_date blank for {len(hits)} cases; "
              f"{recoverable} have a date recoverable from narrative")
    return Finding(len(hits), case_ids, detail)


def r9_row_count(session: Session, ctx: AuditContext) -> Finding:
    raw_n = session.execute(text(f"SELECT count(*) FROM {ctx.raw_table}")).scalar_one()
    cold_n = session.execute(
        text("SELECT count(*) FROM cold_case.cases WHERE dataset_version_id=:dv"),
        {"dv": ctx.dataset_version_id},
    ).scalar_one()
    if raw_n == cold_n:
        return Finding(0, [], f"raw {raw_n} == cold {cold_n}")
    return Finding(abs(raw_n - cold_n), [],
                   f"row-count mismatch: raw {raw_n} vs cold {cold_n}")


def r10_contact_address_mismap(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text(f"""
            SELECT c.case_id, ct.address AS contact_addr,
                   r.agency_address AS agency_addr
            FROM cold_case.cases c
            JOIN {ctx.raw_table} r
              ON r.source_case_id = c.source_case_id
             AND r.dataset_version_id = c.dataset_version_id
            LEFT JOIN cold_case.contact ct ON ct.case_id = c.case_id
            WHERE c.dataset_version_id = :dv
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = []
    for row in rows:
        # Mirror the transform: it writes clean_sentinel(agency_address) into
        # contact.address, so a sentinel agency address ("Unknown"/"N/A"/",")
        # legitimately yields a NULL contact.address — not a mismap.
        expected = clean_sentinel(row.agency_addr)
        if expected is None:
            continue
        if (row.contact_addr or "").strip() != expected:
            hits.append(row.case_id)
    return Finding(len(hits), hits,
                   "contact.address does not carry the reporting-agency address from raw "
                   "(raw.agency_address)")


def r11_case_name_fidelity(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text(f"""
            SELECT c.case_id, c.case_name
            FROM cold_case.cases c
            JOIN {ctx.raw_table} r
              ON r.source_case_id = c.source_case_id
             AND r.dataset_version_id = c.dataset_version_id
            WHERE c.dataset_version_id = :dv
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows if is_sentence_shaped(row.case_name)]
    return Finding(len(hits), hits,
                   "case_name is sentence-shaped (summary leaked into the title field)")


def r12_source_label_honesty(session: Session, ctx: AuditContext) -> Finding:
    cluster = r4_agency_cluster(session, ctx)
    cluster_ids = set(cluster.case_ids)
    if not cluster_ids:
        return Finding(0, [], "no agency-cluster addresses")
    rows = session.execute(
        text("""
            SELECT case_id FROM cold_case.cases
            WHERE dataset_version_id=:dv AND address_source='source'
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows if row.case_id in cluster_ids]
    return Finding(len(hits), hits,
                   "address_source='source' on agency-cluster (non-incident) addresses")


def r13_field_propagation(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text(f"""
            SELECT c.case_id, r.incident_city AS raw_city, c.city AS cold_city
            FROM cold_case.cases c
            JOIN {ctx.raw_table} r
              ON r.source_case_id = c.source_case_id
             AND r.dataset_version_id = c.dataset_version_id
            WHERE c.dataset_version_id = :dv
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows
            if (row.raw_city or "").strip() and not (row.cold_city or "").strip()]
    return Finding(len(hits), hits,
                   "raw incident_city present but cold_case.city NULL (dropped in transform)")


def r14_city_null_rate(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text("""
            SELECT case_id FROM cold_case.cases
            WHERE dataset_version_id=:dv AND (city IS NULL OR btrim(city)='')
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows]
    pct = round(100 * len(hits) / ctx.total_cases, 1) if ctx.total_cases else 0
    return Finding(len(hits), hits, f"city NULL for {len(hits)} cases ({pct}%)")


def r15_extraction_coverage(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text("""
            SELECT c.case_id
            FROM cold_case.cases c
            WHERE c.dataset_version_id=:dv
              AND NOT EXISTS (
                SELECT 1 FROM cold_case.case_extractions_current e
                WHERE e.case_id = c.case_id AND e.prompt_tier = 1
              )
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows]
    return Finding(len(hits), hits, "cases with no Tier-1 extraction row")


def r16_case_type_skew(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text("""
            SELECT case_type, count(*) AS n FROM cold_case.cases
            WHERE dataset_version_id=:dv GROUP BY case_type ORDER BY n DESC
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    breakdown = ", ".join(f"{row.case_type}={row.n}" for row in rows)
    return Finding(0, [],
                   f"case_type distribution: {breakdown} "
                   "(note: classified by FDLE detail label, not search category)")


def r17_geocode_readiness(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text("""
            SELECT case_id, about_text FROM cold_case.cases
            WHERE dataset_version_id=:dv
              AND (latitude IS NULL OR longitude IS NULL)
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows if not narrative_has_address(row.about_text)]
    return Finding(len(hits), hits,
                   "no coordinates AND no extractable address in narrative "
                   "(true map-pin gap)")


def r18_victim_age_gap(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text("""
            SELECT v.case_id
            FROM cold_case.victim v
            JOIN cold_case.cases c ON c.case_id = v.case_id
            WHERE c.dataset_version_id=:dv
              AND v.dob IS NOT NULL
              AND (v.age_text IS NULL OR btrim(v.age_text)='')
              AND v.age_num IS NULL
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows]
    return Finding(len(hits), hits,
                   "victim has dob but no age_text/age_num (derivable field empty)")


def r19_photo_integrity(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text("""
            SELECT p.case_id
            FROM cold_case.case_photo p
            JOIN cold_case.cases c ON c.case_id = p.case_id
            WHERE c.dataset_version_id=:dv
              AND (
                (p.filename IS NOT NULL AND p.storage_path IS NULL)
                OR (p.filename IS NULL AND p.storage_path IS NOT NULL)
              )
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    hits = [row.case_id for row in rows]
    return Finding(len(hits), hits,
                   "case_photo filename/storage_path inconsistency")


def r20_duplicate_victim(session: Session, ctx: AuditContext) -> Finding:
    rows = session.execute(
        text("""
            SELECT v.case_id, lower(btrim(coalesce(v.first_name,'') || '|' ||
                   coalesce(v.last_name,''))) AS k, v.dob
            FROM cold_case.victim v
            JOIN cold_case.cases c ON c.case_id = v.case_id
            WHERE c.dataset_version_id=:dv
        """),
        {"dv": ctx.dataset_version_id},
    ).all()
    seen: dict[tuple[Any, ...], list[int]] = {}
    for row in rows:
        # Skip placeholder names — unidentified decedents ("Unknown", blank) are
        # genuinely distinct people, so grouping them by name+NULL-dob would be a
        # false duplicate. Real names like "Jane Doe" are kept.
        tokens = [t for t in row.k.replace("|", " ").split() if t]
        if not tokens or all(t in _PLACEHOLDER_NAME_TOKENS for t in tokens):
            continue
        seen.setdefault((row.k, row.dob), []).append(row.case_id)
    dup_ids = [cid for ids in seen.values() if len(ids) > 1 for cid in ids]
    return Finding(len(dup_ids), dup_ids,
                   "same victim name+dob across multiple cases")


FL_RULES: list[Rule] = [
    Rule("R1", "title-as-narrative", Severity.HIGH, Layer.L1_RAW, True, r1_title_as_narrative),
    Rule("R2", "empty-narrative", Severity.HIGH, Layer.L1_RAW, False, r2_empty_narrative),
    Rule("R3", "sentinel-address", Severity.MEDIUM, Layer.L1_RAW, False, r3_sentinel_address),
    Rule("R4", "agency-address cluster", Severity.CRITICAL, Layer.L1_RAW, True, r4_agency_cluster),
    Rule("R5", "name-no-comma", Severity.MEDIUM, Layer.L1_RAW, True, r5_name_no_comma),
    Rule("R6", "unnamed-victim", Severity.MEDIUM, Layer.L1_RAW, True, r6_unnamed_victim),
    Rule("R7", "dob-shape", Severity.LOW, Layer.L1_RAW, False, r7_dob_shape),
    Rule("R8", "missing-date", Severity.MEDIUM, Layer.L1_RAW, False, r8_missing_date),
    Rule("R9", "row-count", Severity.CRITICAL, Layer.L2_RECONCILE, False, r9_row_count),
    Rule("R10", "contact-address-mismap", Severity.HIGH, Layer.L2_RECONCILE, False, r10_contact_address_mismap),
    Rule("R11", "case_name-fidelity", Severity.MEDIUM, Layer.L2_RECONCILE, False, r11_case_name_fidelity),
    Rule("R12", "source-label-honesty", Severity.CRITICAL, Layer.L2_RECONCILE, False, r12_source_label_honesty),
    Rule("R13", "field-propagation", Severity.MEDIUM, Layer.L2_RECONCILE, False, r13_field_propagation),
    Rule("R14", "city-null-rate", Severity.MEDIUM, Layer.L3_COLD, False, r14_city_null_rate),
    Rule("R15", "extraction-coverage", Severity.HIGH, Layer.L3_COLD, False, r15_extraction_coverage),
    Rule("R16", "case_type-skew", Severity.INFO, Layer.L3_COLD, False, r16_case_type_skew),
    Rule("R17", "geocode-readiness", Severity.MEDIUM, Layer.L3_COLD, False, r17_geocode_readiness),
    Rule("R18", "victim-age-gap", Severity.LOW, Layer.L3_COLD, False, r18_victim_age_gap),
    Rule("R19", "photo-integrity", Severity.LOW, Layer.L3_COLD, False, r19_photo_integrity),
    Rule("R20", "duplicate-victim", Severity.MEDIUM, Layer.L3_COLD, False, r20_duplicate_victim),
]

SOURCE_RULES: dict[str, SourceAuditConfig] = {
    "cold_case_fl_fdle": SourceAuditConfig(
        source="cold_case_fl_fdle", source_code="FDLE_FL", state="FL", rules=FL_RULES,
    ),
}
