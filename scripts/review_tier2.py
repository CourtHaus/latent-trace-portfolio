"""Interactive CLI review tool for Tier-2 extractions.

Displays one extraction at a time with the narrative, prompts for
per-field verdicts (correct/incorrect/unsure), and stores results
in cold_case.extraction_review.

Usage:
  DATABASE_URL=postgresql://... python scripts/review_tier2.py
  DATABASE_URL=postgresql://... python scripts/review_tier2.py --state MD
  DATABASE_URL=postgresql://... python scripts/review_tier2.py --limit 20 --random
  DATABASE_URL=postgresql://... python scripts/review_tier2.py --resume  (skip already-reviewed)
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.elements import TextClause

FIELDS = [
    ("incident_date", "incident_date_text", "incident_date_raw_phrase", "incident_date_low_confidence"),
    ("address", "address_text", "address_raw_phrase", "address_low_confidence"),
    ("victim_age", "victim_age_text", "victim_age_raw_phrase", "victim_age_low_confidence"),
    ("victim_gender", "victim_gender_text", "victim_gender_raw_phrase", "victim_gender_low_confidence"),
]

def _style(s: str | None, max_len: int = 60) -> str:
    if s is None:
        return "<null>"
    s = str(s)
    if len(s) > max_len:
        s = s[:max_len - 3] + "..."
    return s


def _conf_str(low: bool) -> str:
    return "LOW" if low else "high"


def _pad(s: str, w: int) -> str:
    return s + " " * (w - len(s))


def _print_narrative(text: str | None) -> None:
    if not text:
        print("  [no narrative]")
        return
    lines = text.split("\n")
    for i, line in enumerate(lines):
        print(f"  {line}")
        if i >= 30:
            remaining = len(lines) - i - 1
            if remaining > 0:
                print(f"  ... ({remaining} more lines)")
            break


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Review Tier-2 LLM extractions interactively")
    p.add_argument("--state", type=str, default=None, help="Filter by state code")
    p.add_argument("--limit", type=int, default=None, help="Max cases to review")
    p.add_argument("--random", action="store_true", help="Randomize review order")
    p.add_argument("--resume", action="store_true", help="Skip cases already reviewed by this reviewer")
    p.add_argument("--reviewer", type=str, default=os.environ.get("USER", "unknown"), help="Reviewer identifier")
    p.add_argument(
        "--prompt-hash-prefix",
        default=None,
        help="Optional prompt hash prefix filter. By default, review all Tier-2 prompt hashes.",
    )
    return p.parse_args(argv)


def _prompt_verdict(field_label: str, col_width: int) -> str | None:
    prompt = f"  {_pad(field_label, col_width)} [c]orrect [i]ncorrect [u]nsure [s]kip [q]uit: "
    while True:
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            return "__quit__"
        if answer in ("c", "correct"):
            return "correct"
        if answer in ("i", "incorrect"):
            return "incorrect"
        if answer in ("u", "unsure"):
            return "unsure"
        if answer in ("s", "skip", ""):
            return None
        if answer in ("q", "quit"):
            return "__quit__"


def build_review_query(
    *,
    state: str | None,
    limit: int | None,
    randomize: bool,
    resume: bool,
    reviewer: str,
    prompt_hash_prefix: str | None,
) -> tuple[TextClause, dict[str, Any]]:
    where_clauses = [
        "e.prompt_tier = 2",
        "c.about_text IS NOT NULL AND c.about_text != ''",
    ]
    params: dict[str, Any] = {}

    if prompt_hash_prefix:
        where_clauses.append("LEFT(e.prompt_hash, :hp_len) = :hp")
        params["hp"] = prompt_hash_prefix
        params["hp_len"] = len(prompt_hash_prefix)

    if state:
        where_clauses.append("c.state = :state")
        params["state"] = state

    if resume:
        where_clauses.append(
            "NOT EXISTS (SELECT 1 FROM cold_case.extraction_review r "
            "WHERE r.case_id = e.case_id "
            "AND r.prompt_hash = e.prompt_hash "
            "AND r.reviewer = :reviewer)"
        )
        params["reviewer"] = reviewer

    order = "RANDOM()" if randomize else "c.state, e.case_id"

    sql = f"""
        SELECT e.case_id, c.state, c.case_name,
               e.prompt_hash, c.about_text,
               e.incident_date_text, e.incident_date_raw_phrase, e.incident_date_low_confidence,
               e.address_text, e.address_raw_phrase, e.address_low_confidence,
               e.victim_age_text, e.victim_age_raw_phrase, e.victim_age_low_confidence,
               e.victim_gender_text, e.victim_gender_raw_phrase, e.victim_gender_low_confidence
        FROM cold_case.case_extractions e
        JOIN cold_case.cases c ON c.case_id = e.case_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {order}
    """
    if limit:
        sql += "\n        LIMIT :limit"
        params["limit"] = limit

    return text(sql), params


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    engine = create_engine(url)
    Session = sessionmaker(engine)

    with Session() as session:
        query, params = build_review_query(
            state=args.state,
            limit=args.limit,
            randomize=args.random,
            resume=args.resume,
            reviewer=args.reviewer,
            prompt_hash_prefix=args.prompt_hash_prefix,
        )
        rows = session.execute(query, params).all()

    if not rows:
        print("No extractions to review.")
        return 0

    total = len(rows)
    reviewed = 0
    verdicts: dict[str, str | None] = {}

    for idx, row in enumerate(rows):
        print()
        print("═" * 70)
        print(f"  [{idx + 1}/{total}]  Case #{row.case_id}  |  {row.state}  |  {_style(row.case_name, 40)}")
        print("─" * 70)

        col_w = 22
        field_data: list[tuple[str, str | None, str | None, bool, str]] = []
        for name, val_col, phrase_col, conf_col in FIELDS:
            val = getattr(row, val_col)
            phrase = getattr(row, phrase_col)
            low = getattr(row, conf_col)
            field_data.append((name, val, phrase, low, _conf_str(low)))

        for name, val, phrase, low, conf_str in field_data:
            label = f"{name}:"
            value_part = _style(val, 40)
            phrase_part = f"  phrase: \"{_style(phrase, 50)}\"" if phrase else ""
            conf_part = f"  [{conf_str}]" if low else ""
            print(f"  {_pad(label, col_w)}{value_part}{phrase_part}{conf_part}")

        print("─" * 70)
        _print_narrative(row.about_text)
        print("─" * 70)

        verdicts = {}
        abort = False
        for name, _, _, _, _ in field_data:
            result = _prompt_verdict(name, col_w)
            if result == "__quit__":
                abort = True
                break
            verdicts[name] = result

        if abort:
            print(f"\nSaved {reviewed} reviews so far. Quitting.")
            break

        if all(v is None for v in verdicts.values()):
            print("  [skipped]")
            continue

        with Session() as session:
            session.execute(
                text("""
                    INSERT INTO cold_case.extraction_review
                        (case_id, prompt_hash, prompt_tier, reviewer,
                         verdict_date, verdict_address, verdict_age,
                         verdict_gender, notes)
                    VALUES (:cid, :hash, 2, :reviewer,
                            :vd, :va, :vage, :vg, NULL)
                    ON CONFLICT (case_id, prompt_hash, reviewer)
                    DO UPDATE SET
                        verdict_date = EXCLUDED.verdict_date,
                        verdict_address = EXCLUDED.verdict_address,
                        verdict_age = EXCLUDED.verdict_age,
                        verdict_gender = EXCLUDED.verdict_gender,
                        created_at = NOW()
                """),
                {
                    "cid": row.case_id,
                    "hash": row.prompt_hash,
                    "reviewer": args.reviewer,
                    "vd": verdicts.get("incident_date"),
                    "va": verdicts.get("address"),
                    "vage": verdicts.get("victim_age"),
                    "vg": verdicts.get("victim_gender"),
                },
            )
            session.commit()
        reviewed += 1

    print()
    print(f"Done. {reviewed} cases reviewed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
