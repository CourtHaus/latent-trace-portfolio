"""LLMClient factory pinned to a specific model_id."""

from __future__ import annotations

import os

from casesignal.worker.llm.openai_client import OpenAIClient
from casesignal.worker.llm.protocol import LLMClient

_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_API_KEY = "ollama"  # sentinel; Ollama ignores this, OpenAI SDK requires a non-empty string


def make_llm_client(model_id: str) -> LLMClient:
    """Construct an LLMClient pinned to a specific model_id.

    Uses OPENAI_BASE_URL + OPENAI_API_KEY from env; ignores OPENAI_MODEL since
    callers (e.g. the extraction CLI) pin the model explicitly for reproducibility.

    Temperature is pinned to 0: extractions must be deterministic for auditability
    and the validation gate. Open models (Qwen via Ollama) default to ~1.0, which
    causes the same narrative to yield different classifications run-to-run — that
    breaks the (prompt_hash, model_id) → extraction determinism contract.
    """
    return OpenAIClient(
        base_url=os.environ.get("OPENAI_BASE_URL", _DEFAULT_BASE_URL),
        api_key=os.environ.get("OPENAI_API_KEY", _DEFAULT_API_KEY),
        model=model_id,
        temperature=0.0,
        timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "240")),
        max_retries=int(os.environ.get("OPENAI_MAX_RETRIES", "3")),
    )
