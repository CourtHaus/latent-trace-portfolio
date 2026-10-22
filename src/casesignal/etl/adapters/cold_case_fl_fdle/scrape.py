"""Session scraper for FDLE's JSF/PrimeFaces unsolved-cases portal.

Navigation flow
---------------
``scrape_all``
  Iterates over case types (H / CC / MP). Each type runs in a fresh
  ``PoliteHTTPClient`` session (via ``_new_http_like``) so that JSF
  session state — row-selection, detail view, CAPTCHA consumption — cannot
  bleed across searches.

``scrape_case_type``
  Opens the search page, submits a CAPTCHA-aware search POST, then pages
  through results via repeated ``build_pagination_payload`` POSTs until
  ``row_count`` is satisfied.  Each result row is handed to
  ``_scrape_result_page``.

``_scrape_result_page``
  For every row key: POSTs a row-select payload, follows the PrimeFaces
  partial-response redirect to the detail page, and parses the full
  ``FDLECaseDetail``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import asdict

from casesignal.etl.adapters.cold_case_fl_fdle.jsf import (
    SEARCH_URL,
    FDLECaseDetail,
    FDLEResultPage,
    build_pagination_payload,
    build_row_select_payload,
    build_search_payload,
    parse_captcha_answer,
    parse_case_detail,
    parse_partial_redirect,
    parse_results,
    parse_view_state,
)
from casesignal.etl.services.polite_http import PoliteHTTPClient

logger = logging.getLogger(__name__)

AJAX_HEADERS = {
    "Faces-Request": "partial/ajax",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": SEARCH_URL,
}

DEFAULT_CASE_TYPES = ("H", "CC", "MP")


class FDLEJSFScraper:
    """High-level scraper that manages one JSF session/cookie jar per instance.

    Instantiate with a ``PoliteHTTPClient`` (or leave *http* as ``None`` to
    get one with default settings).  Call ``scrape_all`` to collect every
    ``FDLECaseDetail`` across all case types, or ``scrape_case_type`` to
    scrape a single type in the current session.
    """

    def __init__(self, http: PoliteHTTPClient | None = None) -> None:
        self.http = http or PoliteHTTPClient()

    def scrape_all(
        self,
        *,
        case_types: Iterable[str] = DEFAULT_CASE_TYPES,
        rows_per_page: int = 50,
    ) -> list[FDLECaseDetail]:
        details: list[FDLECaseDetail] = []
        seen: set[str] = set()
        for case_type in case_types:
            # FDLE keeps row-selection/detail state in the JSF session. After
            # navigating to details, a later GET of search.jsf in the same
            # cookie jar can return a detail view with no CAPTCHA field.
            # Isolate each case-type search in a fresh session.
            with _new_http_like(self.http) as case_http:
                case_scraper = FDLEJSFScraper(case_http)
                for detail in case_scraper.scrape_case_type(
                    case_type=case_type,
                    rows_per_page=rows_per_page,
                ):
                    if detail.source_case_id in seen:
                        continue
                    seen.add(detail.source_case_id)
                    details.append(detail)
        return details

    def scrape_case_type(self, *, case_type: str, rows_per_page: int = 50) -> list[FDLECaseDetail]:
        search_html = self.http.get(SEARCH_URL).text
        captcha = parse_captcha_answer(search_html)
        view_state = parse_view_state(search_html)

        response = self.http.post(
            SEARCH_URL,
            data=build_search_payload(
                view_state=view_state,
                captcha_answer=captcha,
                case_type=case_type,
                rows=rows_per_page,
            ),
            headers=AJAX_HEADERS,
        )
        page = parse_results(response.text)
        details = self._scrape_result_page(page)

        total = page.row_count or len(page.rows)
        first = len(page.rows)
        view_state = page.view_state
        while first < total:
            response = self.http.post(
                SEARCH_URL,
                data=build_pagination_payload(
                    view_state=view_state,
                    first_row=first,
                    rows=rows_per_page,
                ),
                headers=AJAX_HEADERS,
            )
            page = parse_results(response.text)
            if not page.rows:
                raise RuntimeError(
                    "FDLE pagination returned zero rows before reaching row_count "
                    f"(first={first}, total={total}, case_type={case_type})."
                )
            details.extend(self._scrape_result_page(page))
            view_state = page.view_state
            first += len(page.rows)
        return details

    def _scrape_result_page(self, result_page: FDLEResultPage) -> list[FDLECaseDetail]:
        details: list[FDLECaseDetail] = []
        for row in result_page.rows:
            response = self.http.post(
                SEARCH_URL,
                data=build_row_select_payload(
                    view_state=result_page.view_state,
                    row_key=row.row_key,
                ),
                headers=AJAX_HEADERS,
            )
            detail_url = parse_partial_redirect(response.text)
            if detail_url is None:
                raise RuntimeError(f"FDLE row-select did not return a detail redirect for {row.row_key}.")
            detail_html = self.http.get(detail_url).text
            details.append(
                parse_case_detail(
                    detail_html,
                    row_key=row.row_key,
                    source_url=detail_url,
                )
            )
        return details


def detail_to_raw_dict(detail: FDLECaseDetail) -> dict[str, object]:
    data = asdict(detail)
    data["photos"] = [asdict(photo) for photo in detail.photos]
    return data


def _new_http_like(http: PoliteHTTPClient) -> PoliteHTTPClient:
    """Return a fresh ``PoliteHTTPClient`` with the same configuration as *http*.

    ``PoliteHTTPClient`` has no ``clone()`` method, so we reconstruct from its
    constructor parameters.  Every argument maps 1-to-1 to a public attribute
    set in ``PoliteHTTPClient.__init__``: ``user_agent``, ``rate_limit_seconds``,
    ``timeout_seconds``, ``max_retries``, ``max_fetch_bytes``,
    ``bypass_robots_hosts``, ``allowed_hosts``.

    The new instance starts with an empty per-host state (``_hosts`` dict and
    fresh ``httpx.Client``), which is the whole point — callers use this to
    begin an isolated JSF session with no shared cookie jar or rate-limit
    history.
    """
    return PoliteHTTPClient(
        user_agent=http.user_agent,
        rate_limit_seconds=http.rate_limit_seconds,
        timeout_seconds=http.timeout_seconds,
        max_retries=http.max_retries,
        max_fetch_bytes=http.max_fetch_bytes,
        bypass_robots_hosts=http.bypass_robots_hosts,
        allowed_hosts=http.allowed_hosts,
    )
