"""Source registration for the UT BCI adapter.

source_hash = SHA256 of canonical sorted "<slug>|<lastmod_iso>" lines from the
sitemap. A different lastmod on any case -> new hash -> new dataset_version,
which is the desired behavior: an upstream content edit triggers a fresh
version. Shared registration lives in etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib

from casesignal.etl.adapters.cold_case_ut.scrape_sitemap import SitemapEntry
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source

_SOURCE_URL = "https://bci.utah.gov/coldcases/"


def register_ut_source(context: PipelineContext) -> None:
    entries: list[SitemapEntry] = context.get_metadata("ut_sitemap_entries") or []
    if not entries:
        raise RuntimeError("ut_sitemap_entries missing; prepare_input must run first.")
    # Record the ACTUAL sitemap that was fetched as the source file (preserves
    # precise provenance for non-default/test sitemaps); fall back to the public
    # landing page when the source definition doesn't pin one.
    sitemap_url = (
        context.get_metadata("source_definition", {}).get("metadata", {}).get("sitemap_url")
    )
    register_cold_case_source(
        context,
        source_hash=canonical_entries_hash(entries),
        source_file_name=sitemap_url or _SOURCE_URL,
        log_label="UT",
    )


def canonical_entries_hash(entries: list[SitemapEntry]) -> str:
    lines = sorted(
        f"{e.detail_url.rstrip('/').rsplit('/', 1)[-1]}|"
        f"{e.lastmod.isoformat() if e.lastmod else ''}"
        for e in entries
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
