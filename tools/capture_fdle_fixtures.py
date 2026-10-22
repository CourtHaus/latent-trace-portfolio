"""One-off: capture real FDLE detail-page HTML as test fixtures.

Run from repo root:
  APP_ENV=dev DATABASE_URL=... python -m tools.capture_fdle_fixtures
Saves raw HTML under data/raw/fdle-fixtures/ for offline parser development.
This hits the live FDLE site via the project's polite_http client.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    from casesignal.etl.adapters.cold_case_fl_fdle.jsf import (
        SEARCH_URL,
        build_row_select_payload,
        build_search_payload,
        parse_captcha_answer,
        parse_partial_redirect,
        parse_results,
        parse_view_state,
    )
    from casesignal.etl.adapters.cold_case_fl_fdle.scrape import AJAX_HEADERS
    from casesignal.etl.services.polite_http import PoliteHTTPClient

    out = Path("data/raw/fdle-fixtures")
    out.mkdir(parents=True, exist_ok=True)

    http = PoliteHTTPClient()
    search_html = http.get(SEARCH_URL).text
    captcha = parse_captcha_answer(search_html)
    view_state = parse_view_state(search_html)
    print(f"captcha solved: {captcha!r}")

    resp = http.post(
        SEARCH_URL,
        data=build_search_payload(
            view_state=view_state, captcha_answer=captcha, case_type="H", rows=50
        ),
        headers=AJAX_HEADERS,
    )
    (out / "search_results_response.txt").write_text(resp.text, encoding="utf-8")
    page = parse_results(resp.text)
    print(f"results rows on page 1: {len(page.rows)}")

    for i, row in enumerate(page.rows[:10]):
        sel = http.post(
            SEARCH_URL,
            data=build_row_select_payload(view_state=page.view_state, row_key=row.row_key),
            headers=AJAX_HEADERS,
        )
        detail_url = parse_partial_redirect(sel.text)
        if detail_url is None:
            print(f"  row {i} ({row.row_key}): no detail redirect, skipping")
            continue
        html_text = http.get(detail_url).text
        fname = f"detail_{i:02d}_rk{row.row_key}.html"
        (out / fname).write_text(html_text, encoding="utf-8")
        print(f"  saved {fname}  (name={row.name!r})")


if __name__ == "__main__":
    main()
