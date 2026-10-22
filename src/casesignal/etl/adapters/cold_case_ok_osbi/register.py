"""Source registration for the OK OSBI adapter.

source_hash = SHA256 over the canonical sorted entry payloads (photos reduced
to stable hints). Shared registration lives in
etl/services/source_registration.py.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.source_registration import register_cold_case_source


def register_ok_source(context: PipelineContext) -> None:
    entries: list[dict[str, Any]] = context.get_metadata("ok_entries") or []
    if not entries:
        raise RuntimeError("ok_entries missing; prepare_input must run first.")
    source_url = context.get_metadata("source_definition", {}).get("metadata", {}).get(
        "source_url"
    )
    register_cold_case_source(
        context,
        source_hash=canonical_entries_hash(entries),
        source_file_name=source_url,
        log_label="OK OSBI",
    )


def canonical_entries_hash(entries: list[dict[str, Any]]) -> str:
    canonical = []
    for entry in entries:
        stable = dict(entry)
        photo = entry.get("photo")
        stable["photo"] = (
            {"filename_hint": photo.get("filename_hint"), "alt": photo.get("alt")}
            if photo
            else None
        )
        canonical.append(json.dumps(stable, sort_keys=True, default=str))
    return hashlib.sha256("\n".join(sorted(canonical)).encode("utf-8")).hexdigest()
