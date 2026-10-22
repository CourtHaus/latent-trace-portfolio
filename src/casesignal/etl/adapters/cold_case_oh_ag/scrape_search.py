"""OH AG search-results enumeration via paginated GET.

The Ohio AG cold-case landing page (`/Law-Enforcement/Local-Law-Enforcement/Cold-Case`)
paginates via a plain `?page=N` GET query parameter. Each page renders ~10
cases with detail-page anchors at `/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/<slug>`.
The page also includes a Kentico pager block that displays `(of NNNN total)`,
giving us the total case count for drift detection.

This module exposes:

- `parse_search_page(html, base_url)` — extract one `SearchResultRow` per
  unique detail-page link on a single page. Filters out "Print Poster"
  Poster.aspx links and the duplicate image/name anchors that point at
  the same detail URL.
- `parse_total_count(html)` — read the `(of N total)` count from the
  pager block. Returns 0 if the marker is absent.
- `paginate_all(polite_http, base_list_url)` — iterate `?page=1..N` until
  a page returns zero new rows. Yields `SearchResultRow` objects.
- `drift_check(baseline, live)` — 5%/20% threshold check used by the
  adapter to detect upstream churn.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from casesignal.etl.services.bs_helpers import attr_str
from casesignal.etl.services.polite_http import PoliteHTTPClient

_DETAIL_PATH_RE = re.compile(
    r"^/?Files/Law-Enforcement/Investigator/Cold-Case/Homicides/" r"[A-Za-z][A-Za-z0-9_\-]*$"
)
_TOTAL_COUNT_RE = re.compile(r"\(of\s+(\d+)\s*\)")
# Soft cap so a runaway pager never hits hundreds of thousands of pages.
_MAX_PAGES = 1000


@dataclass(frozen=True)
class SearchResultRow:
    """One case from the listing page. Minimal: victim name + absolute detail URL."""

    name: str
    detail_url: str


def parse_search_page(html: str, *, base_url: str) -> list[SearchResultRow]:
    """Return one SearchResultRow per unique case on the page.

    `base_url` example: `https://www.ohioattorneygeneral.gov`. Returned
    `detail_url` is absolute. Print-Poster anchors (which point at
    `Poster.aspx?printpath=...`) are filtered out via strict path-shape
    matching.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[SearchResultRow] = []
    seen: set[str] = set()

    # Each case row has two anchors pointing at the same detail URL: an
    # image-link (whose text comes from <img alt="...">) and a name-link
    # (whose text is the victim's name). Iterating top-down and taking
    # the first anchor wins the image; we want the name. Two-pass: first
    # collect every (url, anchor) pair, then for each url pick the anchor
    # whose direct text (without image alt) is non-empty.
    by_url: dict[str, list[Tag]] = {}
    for a in soup.find_all("a"):
        href = (attr_str(a, "href") or "").strip()
        if not href:
            continue
        path = re.sub(r"^https?://[^/]+", "", href)
        if not _DETAIL_PATH_RE.match(path):
            continue
        absolute = urljoin(base_url, href)
        by_url.setdefault(absolute, []).append(a)

    for absolute, anchors in by_url.items():
        if absolute in seen:
            continue
        # Prefer an anchor with no <img> child — that's the name link.
        # Fall back to one with text content. Last resort: alt-text from
        # the image-link's <img>.
        name: str | None = None
        for a in anchors:
            if a.find("img"):
                continue
            text = (a.get_text() or "").strip()
            if text:
                name = text
                break
        if not name:
            # Fall back to alt-text from the image-link anchor
            for a in anchors:
                img = a.find("img")
                if isinstance(img, Tag):
                    alt = attr_str(img, "alt")
                    if alt:
                        name = alt.strip()
                        if name:
                            break
        if not name:
            continue
        seen.add(absolute)
        rows.append(
            SearchResultRow(
                name=re.sub(r"\s+", " ", name),
                detail_url=absolute,
            )
        )

    return rows


def parse_total_count(html: str) -> int:
    """Extract the total case count from the pager `(of NNNN total)` marker.

    Returns 0 if the marker isn't present (e.g. on an empty result page).
    """
    m = _TOTAL_COUNT_RE.search(html)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def paginate_all(
    polite_http: PoliteHTTPClient,
    *,
    base_list_url: str,
    site_base_url: str = "https://www.ohioattorneygeneral.gov",
) -> Iterator[SearchResultRow]:
    """Iterate `?page=1..N` until a page returns zero new rows.

    `polite_http` is expected to expose a `.get(url)` method returning an
    object with a `.text` attribute (mirrors httpx.Response).

    `base_list_url` should be the bare listing URL without a `page` query
    (e.g. `https://www.ohioattorneygeneral.gov/Law-Enforcement/Local-Law-Enforcement/Cold-Case`).
    """
    seen_global: set[str] = set()
    for page_num in range(1, _MAX_PAGES + 1):
        url = base_list_url if page_num == 1 else f"{base_list_url}?page={page_num}"
        resp = polite_http.get(url)
        page_rows = parse_search_page(resp.text, base_url=site_base_url)
        new_this_page = 0
        for r in page_rows:
            if r.detail_url in seen_global:
                continue
            seen_global.add(r.detail_url)
            new_this_page += 1
            yield r
        if new_this_page == 0:
            # Empty page or pager exhausted; stop.
            return


def drift_check(*, baseline: int, live: int) -> Literal["pass", "warn", "abort"]:
    """Compare live case count vs the baseline configured in YAML.

    < 5%: pass. 5-20%: warn. >= 20% or baseline <= 0: abort.
    """
    if baseline <= 0:
        return "abort"
    delta = abs(live - baseline) / baseline
    if delta < 0.05:
        return "pass"
    if delta < 0.20:
        return "warn"
    return "abort"
