"""Parse the Utah BCI WordPress sitemap for the dps_coldcases custom post type.

Sitemap URL: https://bci.utah.gov/wp-sitemap-posts-dps_coldcases-1.xml

Structure (standard sitemap protocol):
  <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
      <loc>https://bci.utah.gov/coldcases/&lt;slug&gt;/</loc>
      <lastmod>2024-04-12T18:23:01+00:00</lastmod>
    </url>
    ...
  </urlset>

A single sitemap covers the full universe at this scale (497 entries verified
2026-05-11; WordPress shards at 2000+). Drift check applies to the TOTAL entry
count (all case types), not the homicide-only subset — case-type is not in
the sitemap.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_URL_PATTERN = re.compile(r"^https://bci\.utah\.gov/coldcases/[a-z0-9-]+/$")


@dataclass(frozen=True)
class SitemapEntry:
    detail_url: str
    lastmod: datetime | None


def parse_sitemap(xml_text: str) -> list[SitemapEntry]:
    """Parse the sitemap XML; emit one entry per <url> with a valid <loc>.

    Entries failing URL-shape validation are logged and skipped (don't abort —
    a malformed entry shouldn't break a 497-entry crawl).
    """
    root = ET.fromstring(xml_text)
    entries: list[SitemapEntry] = []

    for url_el in root.findall(f"{_SITEMAP_NS}url"):
        loc_el = url_el.find(f"{_SITEMAP_NS}loc")
        if loc_el is None or not loc_el.text:
            logger.warning("UT sitemap: skipping <url> with no <loc>")
            continue
        loc = loc_el.text.strip()
        if not _URL_PATTERN.match(loc):
            logger.warning("UT sitemap: skipping <loc>=%r — pattern mismatch", loc)
            continue

        lastmod_el = url_el.find(f"{_SITEMAP_NS}lastmod")
        lastmod: datetime | None = None
        if lastmod_el is not None and lastmod_el.text:
            try:
                lastmod = datetime.fromisoformat(lastmod_el.text.strip())
            except ValueError:
                logger.warning(
                    "UT sitemap: unparseable <lastmod>=%r on %s — leaving NULL",
                    lastmod_el.text,
                    loc,
                )

        entries.append(SitemapEntry(detail_url=loc, lastmod=lastmod))

    return entries


def drift_check(*, baseline: int, live: int) -> str:
    """Return 'silent', 'warn', or 'abort' per the 5%/20% thresholds.

    Drift is computed against the all-types sitemap count, which is a noisier
    signal than CO's typed HOMICIDE-OPEN total. Verdict drives the
    prepare_input log-or-raise decision.

    Returns 'abort' when baseline ≤ 0 (division-by-zero guard).
    """
    if baseline <= 0:
        return "abort"
    delta_pct = abs(live - baseline) / baseline
    if delta_pct > 0.20:
        return "abort"
    if delta_pct > 0.05:
        return "warn"
    return "silent"
