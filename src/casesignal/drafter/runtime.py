"""Shared source traversal for generated adapters and offline verification.

The existing capture walkers discover current URLs; a replay client supplies the
captured responses to those same walkers. Only detail sampling differs: live
ingestion reads every detail, while replay declares its captured sample size.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from casesignal.drafter import session
from casesignal.drafter.shapes.base import CaptureResult, HttpClient
from casesignal.drafter.shapes.fixtures import decode, fixture_path
from casesignal.drafter.shapes.html import capture_html
from casesignal.drafter.shapes.json_feed import capture_json
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.scout.models import Candidate, Channel, FieldSpec, Level, Page

SCHEMA_VERSION = 1
Row = dict[str, Any]
Parser = Callable[..., Any]


def source_spec(candidate: Candidate, shape: str, transport: str) -> dict[str, Any]:
    """No examples or golden values enter the runtime configuration."""
    return dict(
        version=SCHEMA_VERSION,
        index_url=candidate.index_url,
        state=candidate.state,
        channel=candidate.channel.value,
        shape=shape,
        transport=transport,
        dataset_id=candidate.dataset_id,
        detail_url_pattern=candidate.detail_url_pattern,
        fields={
            k: {"page": v.page.value if v.page else "list"} for k, v in candidate.fields.items()
        },
    )


def make_client(spec: Mapping[str, Any], rate_limit: float = 2.0) -> PoliteHTTPClient:
    url = str(spec["index_url"])
    host = urlparse(url).hostname
    if urlparse(url).scheme != "https" or not host:
        raise ValueError("runtime source must have an HTTPS hostname")
    return PoliteHTTPClient(
        rate_limit_seconds=rate_limit,
        allowed_hosts={host},
        bypass_robots_hosts=frozenset(),
        tls_impersonate=spec.get("transport") == "curl_cffi",
    )


@dataclass
class ParsedCorpus:
    records: dict[str, Row]
    listings: list[Row]
    details: list[Row]


def capture_source(
    spec: Mapping[str, Any], client: HttpClient, root: Path, *, detail_sample: int | None = None
) -> tuple[session.CaptureSession, CaptureResult]:
    if spec.get("version") != SCHEMA_VERSION:
        raise ValueError("unsupported runtime contract; re-capture and scaffold")
    candidate = Candidate(
        id="runtime",
        level=Level.STATE,
        state=str(spec["state"]),
        index_url=str(spec["index_url"]),
        channel=Channel(spec["channel"]),
        dataset_id=spec.get("dataset_id"),
        detail_url_pattern=spec.get("detail_url_pattern"),
        fields={
            k: FieldSpec(present=True, page=Page(v["page"]))
            for k, v in spec.get("fields", {}).items()
        },
    )
    held = session.start(
        root, str(spec["shape"]), now="runtime", nonce="run", fixtures_root="fixtures"
    )
    fixtures = root / "fixtures"
    if spec["shape"] == "html":
        result = capture_html(
            candidate,
            client,
            held,
            root,
            fixtures,
            detail_sample=detail_sample if detail_sample is not None else 2**31,
        )
    else:
        result = capture_json(candidate, client, held, root, fixtures)
    if result.truncated or not result.record_list_identified:
        raise ValueError(
            "runtime traversal is incomplete or unidentified; refusing partial ingestion"
        )
    return held, result


def collect(
    spec: Mapping[str, Any],
    client: HttpClient,
    parse_records: Parser,
    parse_detail: Parser,
    *,
    detail_sample: int | None = None,
) -> ParsedCorpus:
    with tempfile.TemporaryDirectory(prefix="casesignal-runtime-") as directory:
        root = Path(directory)
        held, result = capture_source(spec, client, root, detail_sample=detail_sample)
        fixtures = root / "fixtures"
        urls = {f.path: f.url for f in held.fixtures}
        names = {
            name: (str(client.fixtures[url]["path"]) if isinstance(client, ReplayClient) else name)
            for name, url in urls.items()
        }
        by_key: dict[str, Row] = {}
        listings: list[Row] = []
        details: list[Row] = []
        for name in result.listing_paths:
            rows = parse_records(decode((fixtures / name).read_bytes()), base_url=urls[name])
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError("parse_records must return dictionaries")
                listings.append(dict(row))
                by_key[f"{names[name]}#{index}"] = dict(row)
        if len(by_key) != result.records_captured:
            raise ValueError("parser record count differs from source traversal")
        by_url = {f.url: f.path for f in held.fixtures}
        for record in result.records:
            if record.page != "detail":
                continue
            assert record.detail_url is not None
            name = by_url[record.detail_url]
            parsed = parse_detail(decode((fixtures / name).read_bytes()), url=record.detail_url)
            details.append(parsed)
            listing, ordinal = record.key.rsplit("#", 1)
            by_key[f"{names[listing]}#{ordinal}"].update(
                {k: v for k, v in parsed.items() if v is not None}
            )
        return ParsedCorpus(by_key, listings, details)


@dataclass(frozen=True)
class ReplayResponse:
    content: bytes
    status_code: int

    @property
    def text(self) -> str:
        return decode(self.content)


class ReplayClient:
    """No network fallback; every replayed byte must match its capture digest."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = json.loads((root / "capture.json").read_text())
        self.fixtures = {f["url"]: f for f in self.manifest["fixtures"]}
        self.requested: list[str] = []

    def get(self, url: str) -> ReplayResponse:
        if url not in self.fixtures:
            raise ValueError(f"uncaptured request during replay: {url}")
        item = self.fixtures[url]
        raw = fixture_path(self.root, item["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"capture digest mismatch: {item['path']}")
        self.requested.append(url)
        return ReplayResponse(raw, item["status"])

    def close(self) -> None:
        pass


def replay(
    root: Path, spec: Mapping[str, Any], parse_records: Parser, parse_detail: Parser
) -> ParsedCorpus:
    client = ReplayClient(root)
    return collect(
        spec,
        client,
        parse_records,
        parse_detail,
        detail_sample=int(client.manifest["detail_sample"]),
    )
