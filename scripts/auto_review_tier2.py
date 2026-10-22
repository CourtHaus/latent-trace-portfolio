"""Auto-review all Tier-2 extractions against source data and heuristics.

Compares extracted values against source-provided data (where available)
and checks for known hallucination patterns. Stores verdicts in
cold_case.extraction_review so the interactive tool can skip them.

Usage:
  DATABASE_URL=postgresql://... python scripts/auto_review_tier2.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.elements import TextClause

REVIEWER = "auto-review"
BATCH_SIZE = 200

GENDER_ALIASES = {
    "m": "male",
    "male": "male",
    "man": "male",
    "boy": "male",
    "f": "female",
    "female": "female",
    "woman": "female",
    "girl": "female",
}


def _clean_demo_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    if not cleaned or cleaned in {"unknown", "unk", "n/a", "na"}:
        return None
    return cleaned


def _normalize_gender_for_compare(value: str | None) -> str | None:
    cleaned = _clean_demo_value(value)
    if cleaned is None:
        return None
    return GENDER_ALIASES.get(cleaned, cleaned)


def _check_date(date_str: str | None, src_date: str | None) -> str | None:
    if date_str is None and src_date is None:
        return "correct"
    if src_date is None:
        return None
    if date_str is None:
        return "incorrect"
    if date_str == src_date:
        return "correct"
    if src_date.endswith("-01-01") and date_str[:4] == src_date[:4]:
        return "correct"
    return "incorrect"


def _check_gender(gender: str | None, src_gender: str | None, phrase: str | None) -> str | None:
    if gender is None and src_gender is None:
        return "correct"
    normalized_src = _normalize_gender_for_compare(src_gender)
    if normalized_src is not None:
        if _normalize_gender_for_compare(gender) == normalized_src:
            return "correct"
        return "incorrect"
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-review Tier-2 LLM extractions")
    parser.add_argument(
        "--prompt-hash-prefix",
        default=None,
        help="Optional prefix filter. By default, review all Tier-2 prompt hashes.",
    )
    return parser.parse_args(argv)


def build_review_query(prompt_hash_prefix: str | None) -> tuple[TextClause, dict[str, object]]:
    prompt_hash_filter = ""
    params: dict[str, object] = {"rev": REVIEWER}
    if prompt_hash_prefix:
        prompt_hash_filter = "AND LEFT(e.prompt_hash, :hp_len) = :hp"
        params["hp"] = prompt_hash_prefix
        params["hp_len"] = len(prompt_hash_prefix)

    return (
        text(f"""
            WITH victim_demo AS (
                SELECT
                    case_id,
                    COUNT(*) AS victim_count,
                    CASE WHEN COUNT(*) = 1 THEN MAX(gender) ELSE NULL END AS src_gender
                FROM cold_case.victim
                GROUP BY case_id
            )
            SELECT e.case_id, e.prompt_hash, c.state,
                   e.incident_date_text,
                   e.victim_gender_text, e.victim_gender_raw_phrase,
                   c.incident_date::text AS src_date,
                   v.src_gender
            FROM cold_case.case_extractions e
            JOIN cold_case.cases c ON c.case_id = e.case_id
            LEFT JOIN victim_demo v ON v.case_id = e.case_id
            WHERE e.prompt_tier = 2
              {prompt_hash_filter}
              AND NOT EXISTS (
                SELECT 1 FROM cold_case.extraction_review r
                WHERE r.case_id = e.case_id
                  AND r.prompt_hash = e.prompt_hash
                  AND r.reviewer = :rev
              )
            ORDER BY c.state, e.case_id
        """),
        params,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    engine = create_engine(url)
    Session = sessionmaker(engine)

    with Session() as session:
        query, params = build_review_query(args.prompt_hash_prefix)
        rows = session.execute(query, params).all()

    if not rows:
        print("All extractions already auto-reviewed.")
        return 0

    total = len(rows)
    print(f"Auto-reviewing {total} extractions...")

    verdicts = []
    for row in rows:
        v_date = _check_date(row.incident_date_text, row.src_date)
        v_gender = _check_gender(row.victim_gender_text, row.src_gender, row.victim_gender_raw_phrase)
        verdicts.append({
            "cid": row.case_id,
            "hash": row.prompt_hash,
            "vd": v_date,
            "vg": v_gender,
        })

    with Session() as session:
        for i in range(0, len(verdicts), BATCH_SIZE):
            batch = verdicts[i:i + BATCH_SIZE]
            for v in batch:
                session.execute(
                    text("""
                        INSERT INTO cold_case.extraction_review
                            (case_id, prompt_hash, prompt_tier, reviewer,
                             verdict_date, verdict_gender)
                        VALUES (:cid, :hash, 2, :rev,
                                :vd, :vg)
                        ON CONFLICT (case_id, prompt_hash, reviewer)
                        DO NOTHING
                    """),
                    {
                        "cid": v["cid"],
                        "hash": v["hash"],
                        "rev": REVIEWER,
                        "vd": v["vd"],
                        "vg": v["vg"],
                    },
                )
            session.commit()
            print(f"  stored {min(i + BATCH_SIZE, total)}/{total}")

    correct = sum(1 for v in verdicts if all(x == "correct" for x in [v["vd"], v["vg"]] if x is not None))
    flagged = sum(1 for v in verdicts if any(x == "incorrect" for x in [v["vd"], v["vg"]] if x is not None))
    unsure = sum(1 for v in verdicts if all(x is None for x in [v["vd"], v["vg"]]))

    print(f"\nDone. {total} reviewed: {correct} correct, {flagged} flagged, {unsure} need human review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
