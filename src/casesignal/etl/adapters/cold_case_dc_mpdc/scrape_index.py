"""Parse the DC MPDC unsolved-homicides hub page.

The hub lists year links — mostly single-year (e.g., "2020") but
some grouped (e.g., "1971-1990"). Returns a list of
(year_set, absolute_url) tuples. The year_set is a frozenset[int]
covering all years that page is responsible for; this lets the
adapter filter to in-scope years.

Year link text patterns observed on the live hub (2026-05-09):
  - "2024" → year_set={2024}
  - "1991-2000" → year_set={1991, ..., 2000}
  - "1971-1990" → year_set={1971, ..., 1990}
  - "1951-1979" → year_set={1951, ..., 1979}

URL patterns observed:
  - https://mpdc.dc.gov/page/major-caseunsolved-homicides-2026  (absolute)
  - /node/NNNNNN  (relative; most years use this form)

The primary year-detection strategy is to parse the link *text*
(not the href), which avoids false-positives from non-year /node/
links (language pages, legal pages, etc.).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from casesignal.etl.services.bs_helpers import attr_str

# Link text: exactly a 4-digit year in the 1900s or 2000s
_SINGLE_YEAR_RE = re.compile(r"^\s*(19\d{2}|20\d{2})\s*$")

# Link text: a year-range with hyphen, en-dash, or em-dash, optional spaces
# e.g. "1971-1990", "1991 - 2000", "1951–1979"
_RANGE_RE = re.compile(r"^\s*(19\d{2}|20\d{2})\s*[-–—]\s*(19\d{2}|20\d{2})\s*$")


def parse_year_index(html: str, *, base_url: str) -> list[tuple[frozenset[int], str]]:
    """Walk the hub page; return (year_set, absolute_url) tuples.

    Year detection is text-based: only links whose visible text is a
    plain year or year-range are returned. This naturally excludes
    language/legal/nav links that share the /node/ URL pattern.

    Deduplicates by absolute URL (last-write wins for the year_set,
    which is consistent for any given URL).
    """
    soup = BeautifulSoup(html, "html.parser")

    seen: dict[str, frozenset[int]] = {}  # absolute_url → year_set
    for a in soup.find_all("a", href=True):
        href = attr_str(a, "href")
        if href is None:
            continue
        text = " ".join(a.get_text().split()).strip()
        if not text:
            continue

        years = _extract_years_from_text(text)
        if not years:
            continue

        absolute = urljoin(base_url, href)
        seen[absolute] = frozenset(years)

    return [(year_set, url) for url, year_set in seen.items()]


def _extract_years_from_text(text: str) -> set[int]:
    """Return the set of years implied by the link text, or empty set."""
    m = _SINGLE_YEAR_RE.match(text)
    if m:
        return {int(m.group(1))}
    m = _RANGE_RE.match(text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return set(range(lo, hi + 1))
    return set()
