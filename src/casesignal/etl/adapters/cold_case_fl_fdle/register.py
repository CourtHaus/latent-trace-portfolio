"""Source registration for the FL FDLE adapter.

source_hash = SHA256 over the canonical sorted entry payloads (photos reduced to
stable hints). source_file_name is the metadata source_url (FDLE is a JSON API,
not a hardcoded county page). Shared registration lives in
etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source


def register_fl_source(context: PipelineContext) -> None:
    entries: list[dict[str, Any]] = context.get_metadata("fl_entries") or []
    if not entries:
        raise RuntimeError("fl_entries missing; prepare_input must run first.")
    source_url = context.get_metadata("source_definition", {}).get("metadata", {}).get(
        "source_url"
    )
    register_cold_case_source(
        context,
        source_hash=canonical_entries_hash(entries),
        source_file_name=source_url,
        log_label="FL FDLE",
    )


def canonical_entries_hash(entries: list[dict[str, Any]]) -> str:
    canonical = []
    for entry in entries:
        stable = dict(entry)
        stable["photos"] = [
            {
                "filename_hint": p.get("filename_hint"),
                "alt": p.get("alt"),
            }
            for p in entry.get("photos", [])
        ]
        canonical.append(json.dumps(stable, sort_keys=True, default=str))
    return hashlib.sha256("\n".join(sorted(canonical)).encode("utf-8")).hexdigest()
