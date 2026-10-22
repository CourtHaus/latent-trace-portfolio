"""Core extract_case() function. Shared by CLI and queue worker.

Pure-ish: takes a case_id + about_text + an LLMClient, returns a CaseExtraction.
Does NOT write to the DB — callers control transactional boundaries.

Semantic contract (mirrors DB column semantics):
  value = None          → extraction failed (LLM API error / malformed)
  value = "unknown"     → LLM said the narrative doesn't mention the attribute
  value = <enum>        → LLM classified; phrase field may still be low_confidence
                          if the phrase doesn't resolve in about_text

low_confidence meaning (per-field):
  False + offsets populated → clean extraction
  True + value populated    → LLM classified, phrase unresolvable (no source span)
  True + value None         → extraction fully failed (API or malformed); notes explains
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

EXTRACTOR_VERSION = "c1-tier1-v1"


_WEAPON_VALUES = {
    "firearm",
    "knife",
    "blunt",
    "personal",
    "asphyxiation",
    "fire",
    "other",
    "unknown",
}
_LOCATION_VALUES = {
    "residence",
    "vehicle",
    "public_outdoor",
    "commercial",
    "workplace",
    "other",
    "unknown",
}


_EXTRACTION_TOOL_SCHEMA = ToolSchema(
    name="record_extraction",
    description="Record the extracted weapon + location_type classifications.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "required": ["weapon", "weapon_phrase", "location_type", "location_type_phrase"],
        "properties": {
            "weapon": {
                "type": "string",
                "enum": sorted(_WEAPON_VALUES),
            },
            "weapon_phrase": {
                "type": ["string", "null"],
                "description": "Verbatim substring from narrative justifying weapon; null if unknown.",
            },
            "location_type": {
                "type": "string",
                "enum": sorted(_LOCATION_VALUES),
            },
            "location_type_phrase": {
                "type": ["string", "null"],
                "description": "Verbatim substring justifying location_type; null if unknown.",
            },
        },
    },
)


@dataclass(frozen=True)
class ExtractedField:
    value: str | None  # enum value, "unknown", or None if failed
    raw_phrase: str | None
    source_start: int | None
    source_end: int | None
    low_confidence: bool


@dataclass(frozen=True)
class CaseExtraction:
    case_id: int
    weapon: ExtractedField
    location_type: ExtractedField
    extractor_version: str
    prompt_hash: str
    model_id: str
    raw_llm_response: dict[str, Any] | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    notes: str | None
    # True only when the LLM response was unusable (malformed/empty/no
    # tool_calls). Callers MUST treat a failed extraction as a job failure
    # (re-runnable), never persist it as a successful row. A legitimately
    # empty narrative is NOT failed — its fields are "unknown"/None with
    # failed=False.
    failed: bool = False


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_REQUIRED_KEYS = {"weapon", "weapon_phrase", "location_type", "location_type_phrase"}


def _parse_content_as_extraction_json(content: str | None) -> dict[str, Any] | None:
    """Extract the expected JSON object from raw assistant content.

    Some local models (qwen3, DeepSeek-R1 distills) emit the classification
    as plain JSON in content instead of via the tool-call API. They may wrap
    it in <think>...</think> reasoning, markdown fences, or extra prose.
    Strip <think> blocks first, then pull the first {...} block and parse.
    Return the parsed dict only if it has the expected keys.
    """
    if not content:
        return None
    # Strip reasoning-model <think>...</think> blocks.
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
    if not _REQUIRED_KEYS.issubset(parsed.keys()):
        return None
    return parsed


def _failed_field() -> ExtractedField:
    return ExtractedField(
        value=None,
        raw_phrase=None,
        source_start=None,
        source_end=None,
        low_confidence=True,
    )


def _build_extracted_field(
    value: str | None,
    phrase: str | None,
    about_text: str,
    allowed: set[str],
) -> ExtractedField:
    """Build an ExtractedField from an LLM-returned classification + phrase.

    Validates value against the allowed enum; unknown values become None.
    Resolves phrase to offsets; flags low_confidence when resolution fails.
    """
    if value not in allowed:
        # LLM returned a value outside the enum (shouldn't happen with strict
        # schema but defend anyway).
        return ExtractedField(
            value=None,
            raw_phrase=phrase,
            source_start=None,
            source_end=None,
            low_confidence=True,
        )

    if value == "unknown":
        # "unknown" is a valid non-low_confidence answer; phrase is null by
        # contract.
        return ExtractedField(
            value="unknown",
            raw_phrase=None,
            source_start=None,
            source_end=None,
            low_confidence=False,
        )

    start, end, low = resolve_offsets(about_text, phrase)
    if low:
        return ExtractedField(
            value=value,
            raw_phrase=phrase,
            source_start=None,
            source_end=None,
            low_confidence=True,
        )
    return ExtractedField(
        value=value,
        raw_phrase=phrase,
        source_start=start,
        source_end=end,
        low_confidence=False,
    )


def extract_case(
    case_id: int,
    about_text: str,
    llm_client: LLMClient,
    prompt_template: str,
    model_id: str,
) -> CaseExtraction:
    """Extract weapon + location_type from about_text; return CaseExtraction.

    Does NOT write to the DB. LLM API exceptions propagate — the queue
    handler turns them into job status='failed'. A malformed LLM response
    (i.e. server responded but content unusable) still returns a
    CaseExtraction with marker fields so the failure is diagnosable from
    the persisted row.
    """
    prompt_hash = compute_prompt_hash(prompt_template)
    rendered = render_prompt(prompt_template, about_text)
    messages = [LLMMessage(role="user", content=rendered)]
    tools = [_EXTRACTION_TOOL_SCHEMA]

    # 4096 budget accommodates reasoning models (qwen3, DeepSeek-R1)
    # that emit <think>...</think> before the answer. Plain chat models
    # use ~200 tokens for the answer and ignore the rest.
    turn = llm_client.chat(messages=messages, tools=tools, max_tokens=4096)

    # Tool-call path (GPT-class models): preferred.
    args: dict[str, Any] | None
    if turn.finish_reason == "tool_calls" and turn.assistant_message.tool_calls:
        call = turn.assistant_message.tool_calls[0]
        args = call.arguments
        raw_response = {"tool_call": {"name": call.name, "arguments": args}}
    else:
        # Content-JSON fallback: some local models (qwen3, deepseek) emit the
        # answer as raw JSON in content instead of using the tool-call API.
        # Accept a JSON object with the expected extraction keys; treat
        # anything else as truly malformed.
        args = _parse_content_as_extraction_json(turn.assistant_message.content)
        if args is None:
            return CaseExtraction(
                case_id=case_id,
                weapon=_failed_field(),
                location_type=_failed_field(),
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
                failed=True,
            )
        raw_response = {"content_json": {"arguments": args}}

    weapon = _build_extracted_field(
        value=args.get("weapon"),
        phrase=args.get("weapon_phrase"),
        about_text=about_text,
        allowed=_WEAPON_VALUES,
    )
    location_type = _build_extracted_field(
        value=args.get("location_type"),
        phrase=args.get("location_type_phrase"),
        about_text=about_text,
        allowed=_LOCATION_VALUES,
    )

    return CaseExtraction(
        case_id=case_id,
        weapon=weapon,
        location_type=location_type,
        extractor_version=EXTRACTOR_VERSION,
        prompt_hash=prompt_hash,
        model_id=model_id,
        raw_llm_response=raw_response,
        prompt_tokens=None,  # TODO: extend LLMClient protocol to return usage; out of C1 v1 scope
        completion_tokens=None,
        cost_usd=None,
        notes=None,
    )
