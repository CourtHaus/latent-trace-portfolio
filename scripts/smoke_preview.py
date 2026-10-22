#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

DEFAULT_BASE_URL = "https://casesignal-preview.vercel.app"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_MAX_DETAIL_CHECKS = 10
CASE_DETAIL_RE = re.compile(r"^/cold-cases/\d+/[^?#]+$")
CASE_PHOTO_MARKERS = (
    "/api/v1/cold-cases/",
    "%2Fapi%2Fv1%2Fcold-cases%2F",
)


class _PreviewHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.detail_path: str | None = None
        self.detail_paths: list[str] = []
        self.photo_path: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = {name: value for name, value in attrs if value is not None}

        if tag == "a" and self.detail_path is None:
            href = attrs_by_name.get("href", "")
            if CASE_DETAIL_RE.match(href):
                self.detail_path = href

        if tag == "a":
            href = attrs_by_name.get("href", "")
            if CASE_DETAIL_RE.match(href) and href not in self.detail_paths:
                self.detail_paths.append(href)

        if tag == "img" and self.photo_path is None:
            src = attrs_by_name.get("src", "")
            if any(marker in src for marker in CASE_PHOTO_MARKERS):
                self.photo_path = src


@dataclass(frozen=True, slots=True)
class SmokeResult:
    label: str
    url: str
    status_code: int
    content_type: str
    byte_count: int


def extract_first_detail_path(html: str) -> str | None:
    parser = _PreviewHtmlParser()
    parser.feed(html)
    return parser.detail_path


def extract_detail_paths(html: str) -> list[str]:
    parser = _PreviewHtmlParser()
    parser.feed(html)
    return parser.detail_paths


def extract_first_photo_path(html: str) -> str | None:
    parser = _PreviewHtmlParser()
    parser.feed(html)
    return parser.photo_path


def _get_once(
    client: httpx.Client,
    *,
    label: str,
    url: str,
    expected_content_type: str,
) -> tuple[SmokeResult, httpx.Response]:
    response = client.get(url)
    content_type = response.headers.get("content-type", "").split(";")[0]
    result = SmokeResult(
        label=label,
        url=str(response.url),
        status_code=response.status_code,
        content_type=content_type,
        byte_count=len(response.content),
    )

    response.raise_for_status()
    if not content_type.startswith(expected_content_type):
        raise RuntimeError(
            f"{label} returned content-type {content_type!r}, expected {expected_content_type!r}"
        )
    return result, response


def get_with_retries(
    client: httpx.Client,
    *,
    label: str,
    url: str,
    expected_content_type: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_sleep_seconds: float = 5.0,
) -> tuple[SmokeResult, httpx.Response]:
    for attempt in range(1, max_attempts + 1):
        try:
            return _get_once(
                client,
                label=label,
                url=url,
                expected_content_type=expected_content_type,
            )
        except httpx.TimeoutException:
            if attempt == max_attempts:
                raise
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if attempt == max_attempts or status_code not in {502, 503, 504}:
                raise

        if retry_sleep_seconds > 0:
            time.sleep(retry_sleep_seconds)

    raise RuntimeError("unreachable retry state")


def run_smoke_checks(
    *,
    base_url: str,
    timeout_seconds: float,
    check_photo: bool = True,
    max_detail_checks: int = DEFAULT_MAX_DETAIL_CHECKS,
) -> list[SmokeResult]:
    normalized_base_url = base_url.rstrip("/")
    results: list[SmokeResult] = []
    list_html = ""

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        for label, path in [
            ("privacy", "/privacy"),
            ("home", "/"),
            ("list", "/cold-cases"),
            ("map", "/cold-cases/map"),
        ]:
            result, response = get_with_retries(
                client,
                label=label,
                url=urljoin(normalized_base_url, path),
                expected_content_type="text/html",
            )
            results.append(result)
            if label == "list":
                list_html = response.text

        if not check_photo:
            return results

        detail_paths = extract_detail_paths(list_html)[:max_detail_checks]
        if not detail_paths:
            raise RuntimeError("Could not find a case detail link on /cold-cases.")

        for detail_path in detail_paths:
            detail_result, detail_response = get_with_retries(
                client,
                label="detail",
                url=urljoin(normalized_base_url, detail_path),
                expected_content_type="text/html",
            )

            photo_path = extract_first_photo_path(detail_response.text)
            if photo_path is None:
                continue

            results.append(detail_result)
            break
        else:
            raise RuntimeError(
                f"Could not find a case photo image in the first {len(detail_paths)} "
                "case detail pages."
            )

        photo_result, _ = get_with_retries(
            client,
            label="photo",
            url=urljoin(normalized_base_url, photo_path),
            expected_content_type="image/",
        )
        results.append(photo_result)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the CaseSignal preview.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("CASESIGNAL_PREVIEW_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-detail-checks", type=int, default=DEFAULT_MAX_DETAIL_CHECKS)
    parser.add_argument("--skip-photo", action="store_true")
    args = parser.parse_args()

    results = run_smoke_checks(
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        check_photo=not args.skip_photo,
        max_detail_checks=args.max_detail_checks,
    )
    for result in results:
        print(
            f"{result.status_code} {result.content_type} "
            f"{result.byte_count} bytes {result.label}: {result.url}"
        )


if __name__ == "__main__":
    main()
