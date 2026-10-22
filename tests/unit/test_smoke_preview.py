from __future__ import annotations

import httpx

from scripts.smoke_preview import (
    extract_detail_paths,
    extract_first_detail_path,
    extract_first_photo_path,
    get_with_retries,
)


def test_extract_first_detail_path_finds_case_link() -> None:
    html = """
    <html>
      <body>
        <a href="/methodology">Methodology</a>
        <a href="/cold-cases/9701/jane-doe">Jane Doe</a>
      </body>
    </html>
    """

    assert extract_first_detail_path(html) == "/cold-cases/9701/jane-doe"


def test_extract_detail_paths_returns_unique_case_links_in_order() -> None:
    html = """
    <a href="/cold-cases/9701/jane-doe">Jane Doe</a>
    <a href="/cold-cases/9701/jane-doe">Jane Doe again</a>
    <a href="/cold-cases/9702/john-doe">John Doe</a>
    <a href="/cold-cases/map">Map</a>
    """

    assert extract_detail_paths(html) == [
        "/cold-cases/9701/jane-doe",
        "/cold-cases/9702/john-doe",
    ]


def test_extract_first_photo_path_prefers_case_photo_image() -> None:
    html = """
    <html>
      <body>
        <img src="/images/landing/map.jpg" alt="">
        <img
          src="/_next/image?url=%2Fapi%2Fv1%2Fcold-cases%2F9701%2Fphotos%2Fphoto_1.jpg&w=640&q=75"
          alt="Case photo"
        >
      </body>
    </html>
    """

    assert extract_first_photo_path(html) == (
        "/_next/image?url=%2Fapi%2Fv1%2Fcold-cases%2F9701%2Fphotos%2Fphoto_1.jpg&w=640&q=75"
    )


def test_get_with_retries_recovers_from_cold_start_timeout() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("cold start", request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html>ok</html>",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result, response = get_with_retries(
            client,
            label="privacy",
            url="https://casesignal-preview.onrender.com/privacy",
            expected_content_type="text/html",
            max_attempts=2,
            retry_sleep_seconds=0,
        )

    assert attempts == 2
    assert result.status_code == 200
    assert response.text == "<html>ok</html>"
