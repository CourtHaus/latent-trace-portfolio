"""Prompt template loading + hash computation.

prompt_hash = sha256 of the raw template file contents. Any edit to the
template changes the hash; downstream consumers (case_extractions.prompt_hash,
selection queries) detect "new prompt version" automatically.

render_prompt replaces {about_text} with the narrative while leaving other
literal braces intact — unlike Python str.format which would parse { } as
placeholder syntax throughout.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"
# tier1_v2: address-as-geolocation fix — a street address used to locate an
# outdoor body no longer forces `residence` (Step 2 narrowed to private
# curtilage, Step 4 claims public/natural features even with an address). v1
# stays on disk for provenance of rows extracted under it. See
# docs/engineering-decisions.md
_TIER1_PROMPT_PATH = _PROMPTS_DIR / "tier1_v2.txt"
_TIER2_V1_PROMPT_PATH = _PROMPTS_DIR / "tier2_v1.txt"
_TIER2_V2_PROMPT_PATH = _PROMPTS_DIR / "tier2_v2.txt"
_TIER2_V3_PROMPT_PATH = _PROMPTS_DIR / "tier2_v3.txt"
_TIER2_V4_PROMPT_PATH = _PROMPTS_DIR / "tier2_v4.txt"

# Local-only LLM extraction is project policy (see feedback-local-only-llm-extraction
# in project memory). The LLM factory points at Ollama by default; this model id
# tells Ollama which local model to use.
DEFAULT_MODEL_ID = "qwen3:14b"


def get_pinned_model_id() -> str:
    """Return the model_id the extractor should pin for this process.

    Reads EXTRACTION_MODEL_ID from the environment; falls back to
    DEFAULT_MODEL_ID. Callers resolve this once at startup and pass it
    through extract_case + persistence. The (prompt_hash, model_id) pair
    is stored alongside every extraction, so switching models is tracked
    as a distinct extractor version — no migration needed.
    """
    return os.environ.get("EXTRACTION_MODEL_ID", DEFAULT_MODEL_ID)


def load_tier1_prompt_template() -> str:
    """Return the raw Tier-1 prompt template content from disk."""
    return _TIER1_PROMPT_PATH.read_text(encoding="utf-8")


def load_tier2_prompt_template() -> str:
    """Return the raw Tier-2 v1 prompt content from disk.

    Kept stable for the 75 BCounty rows extracted under v1; new
    extractions should use load_tier2_v3_prompt_template().
    """
    return _TIER2_V1_PROMPT_PATH.read_text(encoding="utf-8")


def load_tier2_v2_prompt_template() -> str:
    """Return the raw Tier-2 v2 prompt content from disk.

    DEPRECATED. v2 added victim_race extraction; that field was removed in v3
    after the model was observed deriving race from names despite guardrails
    (see feedback-no-llm-race-inference in project memory). Kept on disk so
    historical (prompt_hash, model_id) audit trails resolve. New extractions
    must use load_tier2_v3_prompt_template.
    """
    return _TIER2_V2_PROMPT_PATH.read_text(encoding="utf-8")


def load_tier2_v3_prompt_template() -> str:
    """Return the raw Tier-2 v3 prompt content from disk.

    v3 = v1 schema (date, address, age, gender) + v2's multi-victim gender
    disambiguation paragraph. NO victim_race extraction. This is the current
    Tier-2 prompt.
    """
    return _TIER2_V3_PROMPT_PATH.read_text(encoding="utf-8")


def load_tier2_v4_prompt_template() -> str:
    """Return the raw Tier-2 v4 prompt content from disk.

    v4 = v3 schema (date, address) + per-victim roster replacing the flat
    victim_age / victim_gender fields. The "victims" array supports
    multi-victim narratives; each element carries name, age, and gender
    with verbatim source phrases. NO victim_race extraction.
    """
    return _TIER2_V4_PROMPT_PATH.read_text(encoding="utf-8")


def compute_prompt_hash(template: str) -> str:
    """Return the sha256 hex digest of the template string."""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


def render_prompt(template: str, about_text: str) -> str:
    """Substitute {about_text} in the template with the narrative.

    Unlike str.format, leaves other literal braces alone — the template's
    schema description contains { } that must NOT be treated as placeholders.
    """
    return template.replace("{about_text}", about_text)
