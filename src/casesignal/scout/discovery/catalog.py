"""Structured-catalog discovery: Socrata Discovery API and ArcGIS Hub search.

Both return dataset ids and exact record counts, so candidates from this channel
carry Confidence.EXACT case counts. State/level/county are left unset here; the
classification subagent resolves scope, agency, and location from the dataset page.
"""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote_plus

from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.scout.models import Candidate, CaseCount, Channel, Confidence, Level

SOCRATA_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
ARCGIS_HUB_URL = "https://hub.arcgis.com/api/v3/search"


def fetch_socrata(client: PoliteHTTPClient, query: str) -> dict[str, Any]:
    resp = client.get(f"{SOCRATA_CATALOG_URL}?q={quote_plus(query)}&only=dataset")
    return cast("dict[str, Any]", resp.json())


def fetch_arcgis(client: PoliteHTTPClient, query: str) -> dict[str, Any]:
    resp = client.get(f"{ARCGIS_HUB_URL}?q={quote_plus(query)}")
    return cast("dict[str, Any]", resp.json())


def parse_socrata(payload: dict[str, Any], seen: set[str]) -> list[Candidate]:
    out: list[Candidate] = []
    for r in payload.get("results", []):
        res = r.get("resource", {})
        ds_id = res.get("id")
        if not ds_id or ds_id in seen:
            continue
        seen.add(ds_id)
        rows = res.get("rowsUpdatedCount")
        out.append(
            Candidate(
                id=ds_id,
                level=Level.COUNTY,  # provisional; subagent confirms actual level
                state="",  # resolved by the classifier
                index_url=r.get("permalink", ""),
                channel=Channel.SOCRATA,
                dataset_id=ds_id,
                page_type="api_json",
                agency=res.get("name"),
                case_count=CaseCount(
                    value=int(rows) if rows is not None else None,
                    confidence=Confidence.EXACT if rows is not None else None,
                    basis="catalog rowsUpdatedCount",
                ),
            )
        )
    return out


def parse_arcgis(payload: dict[str, Any], seen: set[str]) -> list[Candidate]:
    out: list[Candidate] = []
    for item in payload.get("data", []):
        item_id = item.get("id")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        attrs = item.get("attributes", {})
        rows = attrs.get("recordCount")
        out.append(
            Candidate(
                id=item_id,
                level=Level.COUNTY,
                state="",
                index_url=attrs.get("url", ""),
                channel=Channel.ARCGIS,
                dataset_id=item_id,
                page_type="api_json",
                agency=attrs.get("name"),
                case_count=CaseCount(
                    value=int(rows) if rows is not None else None,
                    confidence=Confidence.EXACT if rows is not None else None,
                    basis="hub recordCount",
                ),
            )
        )
    return out
