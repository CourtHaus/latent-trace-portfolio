"""scrape_search — paginated GET enumeration + drift check."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from casesignal.etl.adapters.cold_case_oh_ag.scrape_search import (
    SearchResultRow,
    drift_check,
    paginate_all,
    parse_search_page,
    parse_total_count,
)

_SAMPLE_PAGE_HTML = """
<html>
  <body>
    <div class="PagerControl">
      <div class="PagerResults">Displaying results 1-10 (of 2797)</div>
    </div>
    <ul>
      <li>
        <a href="/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/Exampleton">
          <img src="/x.jpg" alt="Alma Exampleton photo"/>
        </a>
        <a href="/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/Exampleton">Alma Exampleton</a>
        <a href="/Law-Enforcement/Local-Law-Enforcement/Poster.aspx?printpath=/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/Exampleton&classname=Custom.ColdCaseDatabase">Print Poster</a>
      </li>
      <li>
        <a href="/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/Ball-2">Shawn Ball</a>
        <a href="/Law-Enforcement/Local-Law-Enforcement/Poster.aspx?printpath=/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/Ball-2&classname=Custom.ColdCaseDatabase">Print Poster</a>
      </li>
    </ul>
  </body>
</html>
"""


def test_parse_search_page_extracts_one_per_case() -> None:
    rows = parse_search_page(_SAMPLE_PAGE_HTML, base_url="https://www.ohioattorneygeneral.gov")
    assert len(rows) == 2
    assert all(isinstance(r, SearchResultRow) for r in rows)


def test_parse_search_page_uses_name_text_not_image() -> None:
    rows = parse_search_page(_SAMPLE_PAGE_HTML, base_url="https://www.ohioattorneygeneral.gov")
    by_url = {r.detail_url: r.name for r in rows}
    exampleton_url = (
        "https://www.ohioattorneygeneral.gov/Files/Law-Enforcement/"
        "Investigator/Cold-Case/Homicides/Exampleton"
    )
    assert by_url[exampleton_url] == "Alma Exampleton"


def test_parse_search_page_rejects_print_poster_links() -> None:
    rows = parse_search_page(_SAMPLE_PAGE_HTML, base_url="https://www.ohioattorneygeneral.gov")
    for r in rows:
        assert "Poster.aspx" not in r.detail_url
        assert "?" not in r.detail_url
        assert "/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/" in r.detail_url


def test_parse_search_page_dedupes_image_and_name_anchors() -> None:
    rows = parse_search_page(_SAMPLE_PAGE_HTML, base_url="https://www.ohioattorneygeneral.gov")
    urls = [r.detail_url for r in rows]
    assert len(urls) == len(set(urls))


def test_parse_search_page_handles_no_matching_links() -> None:
    html = "<html><body><p>No cases here</p></body></html>"
    rows = parse_search_page(html, base_url="https://www.ohioattorneygeneral.gov")
    assert rows == []


def test_parse_total_count_reads_pager() -> None:
    assert parse_total_count(_SAMPLE_PAGE_HTML) == 2797


def test_parse_total_count_returns_zero_when_absent() -> None:
    assert parse_total_count("<html><body></body></html>") == 0


def test_paginate_all_walks_until_empty() -> None:
    pages = {
        "https://www.ohioattorneygeneral.gov/Law-Enforcement/Local-Law-Enforcement/Cold-Case": _SAMPLE_PAGE_HTML,
        "https://www.ohioattorneygeneral.gov/Law-Enforcement/Local-Law-Enforcement/Cold-Case?page=2": """
            <html><body><ul>
              <li><a href="/Files/Law-Enforcement/Investigator/Cold-Case/Homicides/Lammy">Carla Lammy</a></li>
            </ul></body></html>
        """,
        "https://www.ohioattorneygeneral.gov/Law-Enforcement/Local-Law-Enforcement/Cold-Case?page=3": """
            <html><body><p>empty</p></body></html>
        """,
    }
    polite = MagicMock()

    def fake_get(url: Any) -> Any:
        resp = MagicMock()
        resp.text = pages.get(url, "<html><body></body></html>")
        return resp

    polite.get.side_effect = fake_get

    rows = list(
        paginate_all(
            polite,
            base_list_url=(
                "https://www.ohioattorneygeneral.gov/"
                "Law-Enforcement/Local-Law-Enforcement/Cold-Case"
            ),
        )
    )
    assert len(rows) == 3
    urls = {r.detail_url for r in rows}
    assert any("Exampleton" in u for u in urls)
    assert any("Lammy" in u for u in urls)


def test_paginate_all_dedupes_across_pages() -> None:
    pages = {
        "https://www.ohioattorneygeneral.gov/x": _SAMPLE_PAGE_HTML,
        "https://www.ohioattorneygeneral.gov/x?page=2": _SAMPLE_PAGE_HTML,
    }
    polite = MagicMock()

    def fake_get(url: Any) -> Any:
        resp = MagicMock()
        resp.text = pages.get(url, "<html></html>")
        return resp

    polite.get.side_effect = fake_get

    rows = list(paginate_all(polite, base_list_url="https://www.ohioattorneygeneral.gov/x"))
    assert len(rows) == 2


def test_drift_check_within_5_percent_passes() -> None:
    assert drift_check(baseline=2797, live=2780) == "pass"
    assert drift_check(baseline=2797, live=2900) == "pass"


def test_drift_check_5_to_20_percent_warns() -> None:
    assert drift_check(baseline=2797, live=2500) == "warn"


def test_drift_check_over_20_percent_aborts() -> None:
    assert drift_check(baseline=2797, live=2000) == "abort"
    assert drift_check(baseline=0, live=2797) == "abort"
