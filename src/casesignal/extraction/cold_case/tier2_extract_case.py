"""Tier-2 extractor: incident_date, address, victim_age, victim_gender.

Race extraction was removed in V3. See ``feedback-no-llm-race-inference`` in
project memory and the V3 prompt at ``prompts/tier2_v3.txt`` for the rationale.

Mirrors extract_case.py (Tier-1) for shape but extracts free-form span
values instead of categorical classifications. Same source-offset
machinery (offsets.resolve_offsets), same low_confidence semantics, same
LLMClient protocol.

Tier-2 runs AFTER Tier-1 and produces a separate row in
cold_case.case_extractions with prompt_tier=2. The extraction worker
dispatches based on the prompt_tier in the job payload (Phase D2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from casesignal.extraction.cold_case.offsets import resolve_offsets
from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    render_prompt,
)
from casesignal.worker.llm.protocol import LLMClient, LLMMessage, ToolSchema

EXTRACTOR_VERSION = "c1-tier2-v4"


_GENDER_VALUES = {"M", "F"}


def _coerce_scalar(v: Any) -> str | None:
    """Coerce an LLM tool-call argument to a stripped string or None.

    LLMs occasionally return nested dicts/lists for scalar fields (Qwen has
    been observed returning ``{"value": "M"}`` for victim_gender). The
    downstream _build_*_field helpers assume strings/ints; without coercion
    a dict crashes them (e.g. ``value not in _GENDER_VALUES`` raises
    TypeError on an unhashable dict).

    Non-scalar inputs become None (treated as "no extraction") rather than
    silently passing a malformed value through to canonicalization.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (str, int, float)):
        s = str(v).strip()
        return s or None
    return None


_TIER2_TOOL_SCHEMA = ToolSchema(
    name="record_tier2_extraction",
    description=(
        "Record incident_date, address, and per-victim roster "
        "extracted from the cold-case narrative."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "incident_date",
            "incident_date_phrase",
            "address",
            "address_phrase",
            "victims",
        ],
        "properties": {
            "incident_date": {
                "type": ["string", "null"],
                "description": "ISO 8601 date (YYYY-MM-DD) or null if not stated.",
            },
            "incident_date_phrase": {
                "type": ["string", "null"],
                "description": "Verbatim source phrase justifying the date.",
            },
            "address": {
                "type": ["string", "null"],
                "description": "Full address string as written, or null if absent.",
            },
            "address_phrase": {
                "type": ["string", "null"],
                "description": "Verbatim source phrase justifying the address.",
            },
            "victims": {
                "type": "array",
                "description": "One entry per distinct victim named/described, in narrative order.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "name_phrase", "age", "age_phrase", "gender", "gender_phrase"],
                    "properties": {
                        "name":          {"type": ["string", "null"], "description": "Victim full name as written, or null."},
                        "name_phrase":   {"type": ["string", "null"], "description": "Verbatim source phrase for the name."},
                        "age":           {"type": ["integer", "null"], "description": "Age in years, or null."},
                        "age_phrase":    {"type": ["string", "null"], "description": "Verbatim source phrase for the age."},
                        "gender":        {"type": ["string", "null"], "enum": ["M", "F", None], "description": "'M'/'F'/null."},
                        "gender_phrase": {"type": ["string", "null"], "description": "Verbatim phrase (often a pronoun)."},
                    },
                },
            },
        },
    },
)


@dataclass(frozen=True)
class Tier2Field:
    """One Tier-2 extracted field.

    `value` is typed as Any so the same dataclass can hold strings (date,
    address, gender) and ints (age). Persistence layer downcasts as needed.
    `value=None` means the LLM said "not stated" or the extraction failed
    (notes on the parent CaseTier2Extraction distinguishes those cases).
    """

    value: Any
    raw_phrase: str | None
    source_start: int | None
    source_end: int | None
    low_confidence: bool


@dataclass(frozen=True)
class Tier2Victim:
    """One victim in the narrative roster. ordinal is 1-based narrative order."""

    ordinal: int
    name: Tier2Field          # value = str | None
    victim_age: Tier2Field    # value = int | None
    victim_gender: Tier2Field  # value = "M" | "F" | None


@dataclass(frozen=True)
class CaseTier2Extraction:
    case_id: int
    incident_date: Tier2Field
    address: Tier2Field
    victim_age: Tier2Field
    victim_gender: Tier2Field
    extractor_version: str
    prompt_hash: str
    model_id: str
    raw_llm_response: dict[str, Any] | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    notes: str | None
    victims: tuple[Tier2Victim, ...] = ()
    # True only when the LLM response was unusable. Callers MUST treat a failed
    # extraction as a job failure, never persist it as success. A narrative that
    # genuinely states nothing is NOT failed (its fields are None, failed=False).
    failed: bool = False


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_content_as_tier2_json(content: str | None) -> dict[str, Any] | None:
    """Pull the expected Tier-2 JSON object from raw assistant content.

    Same fallback path Tier-1 uses for local models (qwen3, deepseek-r1)
    that emit JSON in content instead of via tool-calls.

    Unlike the strict tool-call path, any valid JSON dict is accepted —
    missing fields are handled downstream as null/Nones.
    """
    if not content:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    match = _JSON_OBJECT_RE.search(cleaned)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _failed_field() -> Tier2Field:
    return Tier2Field(
        value=None,
        raw_phrase=None,
        source_start=None,
        source_end=None,
        low_confidence=True,
    )


def _build_text_field(
    value: str | None,
    phrase: str | None,
    about_text: str,
) -> Tier2Field:
    """Build a Tier2Field for a string value (incident_date, address)."""
    if value is None or not str(value).strip():
        return Tier2Field(
            value=None,
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=False,  # null is a valid non-low_conf answer
        )
    if phrase is None:
        return Tier2Field(
            value=value,
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=True,  # value present but no source span
        )
    start, end, low = resolve_offsets(about_text, phrase)
    return Tier2Field(
        value=value,
        raw_phrase=phrase,
        source_start=None if low else start,
        source_end=None if low else end,
        low_confidence=low,
    )


def _build_age_field(
    value: str | int | None,
    phrase: str | None,
    about_text: str,
) -> Tier2Field:
    if value is None:
        return Tier2Field(
            value=None,
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=False,
        )
    try:
        age = int(value)
    except (TypeError, ValueError):
        return Tier2Field(
            value=None,
            raw_phrase=phrase,
            source_start=None,
            source_end=None,
            low_confidence=True,
        )
    # Sanity: realistic victim-age bounds. Out-of-range becomes low-conf null.
    if age < 0 or age > 130:
        return Tier2Field(
            value=None,
            raw_phrase=phrase,
            source_start=None,
            source_end=None,
            low_confidence=True,
        )
    if phrase is None:
        return Tier2Field(
            value=age,
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=True,
        )
    start, end, low = resolve_offsets(about_text, phrase)
    return Tier2Field(
        value=age,
        raw_phrase=phrase,
        source_start=None if low else start,
        source_end=None if low else end,
        low_confidence=low,
    )


def _build_gender_field(
    value: str | None,
    phrase: str | None,
    about_text: str,
) -> Tier2Field:
    if value is None:
        return Tier2Field(
            value=None,
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=False,
        )
    if value not in _GENDER_VALUES:
        return Tier2Field(
            value=None,
            raw_phrase=phrase,
            source_start=None,
            source_end=None,
            low_confidence=True,
        )
    if phrase is None:
        return Tier2Field(
            value=value,
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=True,
        )
    start, end, low = resolve_offsets(about_text, phrase)
    return Tier2Field(
        value=value,
        raw_phrase=phrase,
        source_start=None if low else start,
        source_end=None if low else end,
        low_confidence=low,
    )


_NULL_FIELD = Tier2Field(
    value=None,
    raw_phrase=None,
    source_start=None,
    source_end=None,
    low_confidence=False,
)


def _build_victim_roster(
    victims_arg: Any,
    about_text: str,
) -> tuple[Tier2Victim, ...]:
    """Build a tuple of Tier2Victim from the LLM victims array argument.

    Ordinals are 1-based and contiguous over the kept victims (non-dict
    entries are skipped; the ordinal sequence never has gaps).
    Returns an empty tuple when victims_arg is None, not a list, or empty.
    """
    if not isinstance(victims_arg, list):
        return ()
    kept: list[dict[str, Any]] = [v for v in victims_arg if isinstance(v, dict)]
    out: list[Tier2Victim] = []
    for i, v in enumerate(kept, start=1):
        out.append(
            Tier2Victim(
                ordinal=i,
                name=_build_text_field(
                    _coerce_scalar(v.get("name")),
                    _coerce_scalar(v.get("name_phrase")),
                    about_text,
                ),
                victim_age=_build_age_field(
                    _coerce_scalar(v.get("age")),
                    _coerce_scalar(v.get("age_phrase")),
                    about_text,
                ),
                victim_gender=_build_gender_field(
                    _coerce_scalar(v.get("gender")),
                    _coerce_scalar(v.get("gender_phrase")),
                    about_text,
                ),
            )
        )
    return tuple(out)


def extract_case_tier2(
    case_id: int,
    about_text: str,
    llm_client: LLMClient,
    prompt_template: str,
    model_id: str,
) -> CaseTier2Extraction:
    """Extract Tier-2 fields from about_text; return CaseTier2Extraction.

    Does NOT write to the DB. On LLM API failure, all fields come back
    failed (value=None, low_confidence=True) and notes is populated.
    """
    prompt_hash = compute_prompt_hash(prompt_template)
    rendered = render_prompt(prompt_template, about_text)
    messages = [LLMMessage(role="user", content=rendered)]
    tools = [_TIER2_TOOL_SCHEMA]

    # LLM API exceptions propagate — the queue handler turns them into
    # job status='failed'. Only malformed/unparseable LLM responses return
    # a CaseTier2Extraction with marker fields (see below).
    turn = llm_client.chat(messages=messages, tools=tools, max_tokens=4096)

    args: dict[str, Any] | None
    if turn.finish_reason == "tool_calls" and turn.assistant_message.tool_calls:
        call = turn.assistant_message.tool_calls[0]
        args = call.arguments
        raw_response = {"tool_call": {"name": call.name, "arguments": args}}
    else:
        args = _parse_content_as_tier2_json(turn.assistant_message.content)
        if args is None:
            return CaseTier2Extraction(
                case_id=case_id,
                incident_date=_failed_field(),
                address=_failed_field(),
                victim_age=_failed_field(),
                victim_gender=_failed_field(),
                extractor_version=EXTRACTOR_VERSION,
                prompt_hash=prompt_hash,
                model_id=model_id,
                raw_llm_response={
                    "finish_reason": turn.finish_reason,
                    "malformed_reason": turn.malformed_reason,
                    "content": turn.assistant_message.content,
                },
                prompt_tokens=None,
                completion_tokens=None,
                cost_usd=None,
                notes=f"Malformed LLM response: {turn.malformed_reason or 'no tool_calls'}",
                victims=(),
                failed=True,
            )
        raw_response = {"content_json": {"arguments": args}}

    if "victims" in args:
        # v4 path: the response contains a per-victim roster array.
        # An explicit empty list (victims: []) is valid and means zero victims.
        roster = _build_victim_roster(args.get("victims"), about_text)
        # Back-compat scalar fields: populated from the sole victim when there
        # is exactly one; null (non-low-conf) for zero or multiple victims.
        if len(roster) == 1:
            scalar_age = roster[0].victim_age
            scalar_gender = roster[0].victim_gender
        else:
            scalar_age = _NULL_FIELD
            scalar_gender = _NULL_FIELD
    else:
        # v3 fallback: the response uses the old scalar keys
        # (victim_age / victim_age_phrase / victim_gender / victim_gender_phrase,
        # no victims array).  Restore prior behavior so the queued worker (still
        # loading the v3 prompt) doesn't silently lose demographic extractions.
        scalar_age = _build_age_field(
            _coerce_scalar(args.get("victim_age")),
            _coerce_scalar(args.get("victim_age_phrase")),
            about_text,
        )
        scalar_gender = _build_gender_field(
            _coerce_scalar(args.get("victim_gender")),
            _coerce_scalar(args.get("victim_gender_phrase")),
            about_text,
        )
        # Build a single-element roster so downstream roster-aware code
        # (victim reconciliation) sees a consistent non-empty tuple.
        # v3 has no per-victim name field, so name is the null Tier2Field.
        roster = (
            Tier2Victim(
                ordinal=1,
                name=_NULL_FIELD,
                victim_age=scalar_age,
                victim_gender=scalar_gender,
            ),
        )

    return CaseTier2Extraction(
        case_id=case_id,
        incident_date=_build_text_field(
            value=_coerce_scalar(args.get("incident_date")),
            phrase=_coerce_scalar(args.get("incident_date_phrase")),
            about_text=about_text,
        ),
        address=_build_text_field(
            value=_coerce_scalar(args.get("address")),
            phrase=_coerce_scalar(args.get("address_phrase")),
            about_text=about_text,
        ),
        victim_age=scalar_age,
        victim_gender=scalar_gender,
        extractor_version=EXTRACTOR_VERSION,
        prompt_hash=prompt_hash,
        model_id=model_id,
        raw_llm_response=raw_response,
        prompt_tokens=None,
        completion_tokens=None,
        cost_usd=None,
        notes=None,
        victims=roster,
    )
