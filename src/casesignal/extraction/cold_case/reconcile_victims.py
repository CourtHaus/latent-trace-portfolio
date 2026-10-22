"""Multi-victim reconciliation: correct ``cold_case.victim`` rows from a Tier-2
narrative roster.

Phase 1 is **identity only** — this module corrects victim *row structure and
names* (split garbled rows, recover dropped victims) and binds the
``victim_extraction`` provenance rows to the displayed cards via ``victim_id``.
It writes **no** age/gender to ``cold_case.victim`` (that is the separate promotion step; see promote_demographics).

The planning step :func:`plan_reconciliation` is a PURE function (no DB) so the
safety invariants can be exercised exhaustively in unit tests. :func:`apply_
reconciliation` is the thin DB wrapper that executes a plan.

Hard invariants (must hold in every branch):
  - **Never act on an empty roster** — an empty plan is returned.
  - **Never delete an existing row unless it is detected garbled AND the roster
    has >1 victim.** "Garbled" means the existing full name contains ``" and "``
    or ``"&"`` (a concatenation of multiple people into one row).
  - A destructive **replace** (delete + creates) only triggers when
    ``len(roster) > 1`` (guards a legitimate single-victim name with "and").
  - Existing rows matched to a roster entry are **kept and linked**, never
    deleted.
  - Dropped victims are **recovered** (created) only when the roster legitimately
    has more victims than existing rows — except in the garbled-replace branch,
    where all unmatched roster entries are created to replace the deleted row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_WS_RE = re.compile(r"\s+")


@dataclass
class ReconcilePlan:
    """A pure, DB-free description of the reconciliation to apply.

    - ``creates``: ``{"name", "ordinal"}`` rows to INSERT into ``cold_case.victim``.
    - ``deletes``: ``victim_id`` values to DELETE.
    - ``links``: ``(victim_id, ordinal)`` pairs binding an *existing* row to its
      matched roster ordinal. (Created rows are linked to their own ordinal by
      the apply step, using the new ``victim_id``.)
    """

    creates: list[dict[str, Any]] = field(default_factory=list)
    deletes: list[int] = field(default_factory=list)
    links: list[tuple[int, int]] = field(default_factory=list)


def _norm(s: str | None) -> str:
    """Lowercase + collapse internal whitespace; ``None`` -> empty string."""
    return _WS_RE.sub(" ", (s or "").strip()).lower()


def _full_name(row: dict[str, Any]) -> str:
    """Normalized ``"first last"`` for an existing victim row."""
    parts = [row.get("first_name") or "", row.get("last_name") or ""]
    return _norm(" ".join(p for p in parts if p))


def _surname(name: str) -> str:
    """Last whitespace-delimited token of a normalized name ("" if none)."""
    toks = _norm(name).split()
    return toks[-1] if toks else ""


def _first_tokens(name: str) -> set[str]:
    """All-but-last tokens of a normalized name (the given/middle names)."""
    toks = _norm(name).split()
    return set(toks[:-1])


def _is_garbled(row: dict[str, Any]) -> bool:
    """True when the existing name concatenates multiple people into one row.

    Signal: the full name contains ``" and "`` or ``"&"``. This is the only
    condition under which a source-provided row may be deleted, and even then
    only when the roster has >1 victim (enforced in :func:`plan_reconciliation`).
    """
    name = _full_name(row)
    return " and " in name or "&" in name


def _matches(row: dict[str, Any], roster_name: str) -> bool:
    """Principled name match between an existing row and a roster entry.

    Matches when the normalized full names are equal, OR when they are
    surname-anchored: same surname AND at least one shared given-name token.
    This recognizes "Jerry Marshall" == "Jerry Marshall" and tolerates middle
    names / ordering, without matching unrelated people who merely share a
    surname (e.g. "Joseph Selby" vs "Betty Selby") or a first name.
    """
    a = _full_name(row)
    b = _norm(roster_name)
    if not a or not b:
        return False
    if a == b:
        return True
    sn_a, sn_b = _surname(a), _surname(b)
    if sn_a and sn_a == sn_b:
        if _first_tokens(a) & _first_tokens(b):
            return True
    return False


def plan_reconciliation(existing: list[dict[str, Any]], roster: list[dict[str, Any]]) -> ReconcilePlan:
    """Plan how to reconcile existing victim rows against a Tier-2 roster.

    ``existing``: ``[{"victim_id", "first_name", "last_name"}, ...]``
    ``roster``:   ``[{"ordinal", "name"}, ...]`` (narrative order)

    Returns a :class:`ReconcilePlan`. See the module docstring for the invariants
    this guarantees. Identity only — no demographics are planned or written.
    """
    plan = ReconcilePlan()

    # Invariant: never act on an empty roster.
    if not roster:
        return plan

    garbled = [r for r in existing if _is_garbled(r)]

    # --- Branch (b): garbled replace. Only destructive when roster > 1. ---
    if garbled and len(roster) > 1:
        clean = [r for r in existing if not _is_garbled(r)]
        # Delete every garbled row (it concatenates multiple people).
        plan.deletes = [r["victim_id"] for r in garbled]
        # Keep + link clean existing rows that match a roster entry.
        matched_ordinals: set[int] = set()
        for row in clean:
            for entry in roster:
                if entry["ordinal"] in matched_ordinals:
                    continue
                if _matches(row, entry["name"]):
                    plan.links.append((row["victim_id"], entry["ordinal"]))
                    matched_ordinals.add(entry["ordinal"])
                    break
        # Create every roster entry not already covered by a kept row.
        for entry in roster:
            if entry["ordinal"] not in matched_ordinals:
                plan.creates.append({"name": entry["name"], "ordinal": entry["ordinal"]})
        return plan

    # --- General branch: match existing -> roster, never destructive. ---
    matched_ordinals = set()
    matched_existing_ids: set[int] = set()
    for row in existing:
        for entry in roster:
            if entry["ordinal"] in matched_ordinals:
                continue
            if _matches(row, entry["name"]):
                plan.links.append((row["victim_id"], entry["ordinal"]))
                matched_ordinals.add(entry["ordinal"])
                matched_existing_ids.add(row["victim_id"])
                break

    # 1:1 fallback: exactly one existing row, one roster entry, no name match.
    # Treat as the same lone victim re-spelled by the LLM — link, never create.
    if (
        len(existing) == 1
        and len(roster) == 1
        and not plan.links
    ):
        plan.links.append((existing[0]["victim_id"], roster[0]["ordinal"]))
        return plan

    # Recover dropped victims: create unmatched roster entries ONLY when the
    # roster legitimately has more victims than existing rows. This avoids
    # spurious creates on a same-size name mismatch (which is a re-spelling,
    # not a dropped victim).
    if len(roster) > len(existing):
        for entry in roster:
            if entry["ordinal"] not in matched_ordinals:
                plan.creates.append({"name": entry["name"], "ordinal": entry["ordinal"]})

    return plan


def _split_name(name: str) -> tuple[str, str | None]:
    """Split a full name into ``(first_name, last_name)`` on the LAST space.

    A single token becomes ``(token, None)``. Whitespace is collapsed first so a
    trailing/leading space never produces an empty part.
    """
    cleaned = _WS_RE.sub(" ", (name or "").strip())
    if " " not in cleaned:
        return cleaned, None
    first, last = cleaned.rsplit(" ", 1)
    return first, last


def apply_reconciliation(
    session: Session,
    case_id: int,
    plan: ReconcilePlan,
    *,
    model_id: str,
    prompt_hash: str,
) -> None:
    """Execute a :class:`ReconcilePlan` against the DB. Caller controls commit.

    Phase-1 identity only: created ``cold_case.victim`` rows carry first/last
    name and case_id; **no age/gender is written** (demographics are filled by
    promote_demographics, which the callers run right after this). Steps:

    1. INSERT each ``plan.creates`` row (name split on the last space), capturing
       its new ``victim_id`` via ``RETURNING``.
    2. DELETE each ``plan.deletes`` ``victim_id``.
    3. LINK ``victim_extraction.victim_id`` to the displayed card:
       - each created row links its OWN new ``victim_id`` to its ordinal;
       - each ``plan.links`` ``(victim_id, ordinal)`` links an existing row.

    Ordinals on ``plan.creates`` and ``plan.links`` are authoritative for the
    linking step.

    ``model_id`` and ``prompt_hash`` scope the link UPDATE to only the
    *current* extraction's rows, so historical rows for the same
    ``(case_id, victim_ordinal)`` from prior prompt/model versions are not
    overwritten (their ``victim_id`` pointers remain intact).
    """

    def _link(victim_id: int, ordinal: int) -> None:
        session.execute(
            text("""
                UPDATE cold_case.victim_extraction
                   SET victim_id = :vid
                 WHERE case_id = :cid
                   AND victim_ordinal = :ord
                   AND model_id = :mid
                   AND prompt_hash = :ph
            """),
            {"vid": victim_id, "cid": case_id, "ord": ordinal, "mid": model_id, "ph": prompt_hash},
        )

    # 1. Create new victim rows (identity only).
    for create in plan.creates:
        if not (create.get("name") or "").strip():
            continue
        first, last = _split_name(create["name"])
        new_id = session.execute(
            text("""
                INSERT INTO cold_case.victim (case_id, first_name, last_name)
                VALUES (:cid, :first, :last)
                RETURNING victim_id
            """),
            {"cid": case_id, "first": first, "last": last},
        ).scalar_one()
        # 3a. Link the created row to its own ordinal.
        _link(new_id, create["ordinal"])

    # 2. Delete garbled rows.
    for victim_id in plan.deletes:
        session.execute(
            text("DELETE FROM cold_case.victim WHERE victim_id = :id"),
            {"id": victim_id},
        )

    # 3b. Link existing kept rows to their matched ordinal.
    for victim_id, ordinal in plan.links:
        _link(victim_id, ordinal)
