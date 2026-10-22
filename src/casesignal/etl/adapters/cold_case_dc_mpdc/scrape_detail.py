"""Parse a DC MPDC case detail page.

Detail pages are Drupal nodes (/node/NNNNNN). Each has:
  - A short narrative paragraph (one sentence: e.g., "Mr. X was shot
    and killed in the 5200 block of Y.")
  - An attachment link to the PDF reward flier
  - Translation links (Spanish/French/etc.) — we ignore these
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from casesignal.etl.services.bs_helpers import attr_str


@dataclass(frozen=True)
class DetailContents:
    narrative: str | None
    pdf_url: str | None


def parse_detail_page(html: str, *, base_url: str) -> DetailContents:
    """Walk the detail page; extract narrative + PDF flier URL."""
    soup = BeautifulSoup(html, "html.parser")

    # PDF URL: first <a href="...pdf"> link
    pdf_url: str | None = None
    for a in soup.find_all("a", href=True):
        href = attr_str(a, "href")
        if href and href.lower().endswith(".pdf"):
            pdf_url = urljoin(base_url, href)
            break

    # Narrative: walk paragraphs, take the first substantial one that
    # looks like a homicide description (contains a date + name pattern,
    # or "killed/shot/stabbed/homicide").
    narrative: str | None = None
    for p in soup.find_all("p"):
        text = " ".join(p.get_text().split())
        if not text or len(text) < 30:
            continue
        lower = text.lower()
        # Skip boilerplate
        if any(
            skip in lower
            for skip in (
                "anyone with information",
                "report.com",
                "share this page",
                "translation",
            )
        ):
            continue
        # Looks like a narrative paragraph
        if any(kw in lower for kw in ("killed", "shot", "stabbed", "homicide", "died")):
            narrative = text
            break

    return DetailContents(narrative=narrative, pdf_url=pdf_url)
