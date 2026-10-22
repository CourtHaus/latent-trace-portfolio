"""Parse one CO CBI search-results page (paginated POST).

Each page lists ~5–10 cases as <a href="casedetail.html?id={id}"
aria-label="Cold case file for {name}"> anchors.  The overall total
count is in a "Displaying N through M of NNNN total cases." element.

Drift check thresholds (from spec):
  Δ ≤ 5%       → silent
  5% < Δ ≤ 20% → warn
  Δ > 20%      → abort
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from casesignal.etl.services.bs_helpers import attr_str

logger = logging.getLogger(__name__)


_ID_HREF_RE = re.compile(r"casedetail\.html\?id=(\d+)")
_LABEL_NAME_RE = re.compile(r"Cold case file for\s+(.+)", re.IGNORECASE)
# Anchored to "of NNNN total" to avoid false matches against address numbers
# in case narrative text (e.g. "outside of 4500 Mariposa Street").
_TOTAL_COUNT_RE = re.compile(r"of\s+(\d{1,7})\s+total", re.IGNORECASE)


@dataclass(frozen=True)
class SearchResultRow:
    name: str
    detail_id: int
    detail_url: str


def parse_total_count(html: str) -> int:
    """Extract the 'of NNNN total' count from a search-results page.

    Returns 0 if the pattern is not found.
    """
    m = _TOTAL_COUNT_RE.search(html)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def parse_search_page(html: str, *, base_url: str) -> list[SearchResultRow]:
    """Walk anchors; emit one deduplicated row per detail link with a valid ID.

    Anchors without aria-label fall back to inner text; anchors with neither
    are silently skipped.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResultRow] = []
    seen_ids: set[int] = set()

    for a in soup.find_all("a", href=True):
        href = attr_str(a, "href")
        if href is None:
            continue
        m = _ID_HREF_RE.search(href)
        if not m:
            continue
        try:
            detail_id = int(m.group(1))
        except ValueError:
            continue
        if detail_id in seen_ids:
            continue
        seen_ids.add(detail_id)

        # Name primarily from aria-label="Cold case file for {name}"
        aria = attr_str(a, "aria-label") or ""
        name_match = _LABEL_NAME_RE.search(aria)
        if name_match:
            name = " ".join(name_match.group(1).split())
        else:
            # Fallback: anchor inner text (e.g. if aria-label absent)
            name = " ".join(a.get_text().split())
        if not name:
            logger.debug("Skipping detail_id=%d — no name found", detail_id)
            continue

        absolute = urljoin(base_url, href)
        out.append(
            SearchResultRow(
                name=name,
                detail_id=detail_id,
                detail_url=absolute,
            )
        )

    return out


def drift_check(*, baseline: int, live: int) -> str:
    """Return 'silent', 'warn', or 'abort' per the 5%/20% thresholds.

    Returns 'abort' when baseline ≤ 0 (division-by-zero guard; treat as fatal).
    """
    if baseline <= 0:
        return "abort"
    delta_pct = abs(live - baseline) / baseline
    if delta_pct > 0.20:
        return "abort"
    if delta_pct > 0.05:
        return "warn"
    return "silent"
