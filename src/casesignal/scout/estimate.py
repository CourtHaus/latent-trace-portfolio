"""Case-count estimation ladder and plottability heuristic (pure)."""

from __future__ import annotations

import re

from casesignal.scout.models import CaseCount, Confidence, FieldSpec, Location

# Anchor the "of N" total to a results context so it does NOT fire on a
# pagination footer like "Page 1 of 13" (which would stamp the page count at the
# EXACT rung and outrank everything). Accept either the range form
# ("<A> to <B> of <N>") or an "of <N>" followed by a results keyword.
_TOTAL_RE = re.compile(
    r"\d+\s+to\s+\d+\s+of\s+([\d,]{1,7})\b"
    r"|\bof\s+([\d,]{1,7})\s+(?:results|cases|records|entries)\b",
    re.IGNORECASE,
)
_CARD_RE = re.compile(r'class="(?:case|teaser|result|card)\b')
_PAGINATION_RE = re.compile(r'(rel="next"|class="pag|page=\d+|Next\s*&raquo;)', re.IGNORECASE)


def estimate_count_from_listing(html: str, api_count: int | None = None) -> CaseCount:
    if api_count is not None:
        return CaseCount(value=api_count, confidence=Confidence.EXACT, basis="catalog api count")
    m = _TOTAL_RE.search(html)
    if m:
        total = m.group(1) or m.group(2)
        return CaseCount(
            value=int(total.replace(",", "")),
            confidence=Confidence.EXACT,
            basis="stated 'of N' total",
        )
    if _PAGINATION_RE.search(html):
        return CaseCount(
            value=None,
            confidence=Confidence.PROBED,
            basis="paginated; probe to last page at fetch time",
        )
    visible = len(_CARD_RE.findall(html))
    return CaseCount(
        value=visible,
        confidence=Confidence.VISIBLE,
        basis="page-1 visible card count (likely undercount)",
    )


def estimate_plottability(fields: dict[str, FieldSpec]) -> tuple[float, str]:
    def structured(name: str) -> bool:
        f = fields.get(name)
        return bool(f and f.present and f.location == Location.STRUCTURED)

    def narrative(name: str) -> bool:
        f = fields.get(name)
        return bool(f and f.present and f.location == Location.NARRATIVE)

    if structured("county"):
        return 1.0, "county structured at source (landmark floor)"
    if structured("city") or structured("address"):
        return 0.9, "city/address structured at source"
    if narrative("county") or narrative("city"):
        return 0.5, "location narrative-only (Tier-2 extraction dependent)"
    return 0.2, "no usable location signal"
