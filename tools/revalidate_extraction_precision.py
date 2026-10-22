"""Re-measure Tier-1 extraction precision/recall against the validation set
using the CURRENT pinned model (qwen3:14b), live via Ollama, and (with
--record) regenerate the DB-independent ship-gate fixture.

Why this exists: the methodology page's "extraction precision" figure and the
CI ship-gate (`tests/unit/test_cold_case_extraction_validation_gate.py`) both
replay recorded LLM responses. This script runs the labeled cases through the
live current model, prints the real precision/recall, and (with --record)
rewrites the recorded fixture so the gate replays the model we actually ship.

Anchoring: labels are keyed by (state, source_case_id) -- the stable
source-assigned id. We look up each case's CURRENT about_text by that key, so
re-ingests (which rotate the serial case_id) no longer break the lookup. The
recorded fixture embeds about_text, so the ship-gate itself needs no DB.

Run (needs the local Ollama GPU backend up and DATABASE_URL set):

    uv run python tools/revalidate_extraction_precision.py            # measure + print
    uv run python tools/revalidate_extraction_precision.py --record   # also rewrite the fixture

Pure local inference, $0. ~30 calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from casesignal.extraction.cold_case.extract_case import (
    _parse_content_as_extraction_json,
    extract_case,
)
from casesignal.extraction.cold_case.metrics import (
    FieldMetrics,
    PredictedLabeled,
    compute_field_metrics,
)
from casesignal.extraction.cold_case.prompt_loader import (
    get_pinned_model_id,
    load_tier1_prompt_template,
)
from casesignal.extraction.cold_case.validation import ValidationLabel, load_validation_labels
from casesignal.worker.llm.factory import make_llm_client

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RECORDED_RESPONSES = (
    _REPO_ROOT / "data" / "validation" / "cold_case_extraction_recorded_responses.json"
)


class _Pair:
    """Minimal (predicted, labeled) pair for compute_field_metrics."""

    def __init__(self, predicted: str | None, labeled: str) -> None:
        self.predicted = predicted
        self.labeled = labeled


class _RecordingClient:
    """Wrap the live client; capture each call's tool-call arguments by key so
    we can persist them as the replay fixture."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.last_key: str | None = None
        self.records: dict[str, dict[str, Any]] = {}

    def chat(self, messages: Any, tools: Any, max_tokens: Any = 2048) -> Any:
        turn = self.inner.chat(messages=messages, tools=tools, max_tokens=max_tokens)
        assert self.last_key is not None
        # Capture the args dict the extractor will actually use, from EITHER
        # path. qwen3/deepseek commonly emit content-JSON instead of a tool
        # call; extract_case handles both, so the recording must too.
        if turn.finish_reason == "tool_calls" and turn.assistant_message.tool_calls:
            self.records[self.last_key] = turn.assistant_message.tool_calls[0].arguments
        else:
            parsed = _parse_content_as_extraction_json(turn.assistant_message.content)
            if parsed is not None:
                self.records[self.last_key] = parsed
        return turn


def _fmt(name: str, m: FieldMetrics) -> str:
    return (
        f"{name:14s} precision {m.precision:6.1%}  recall {m.recall:6.1%}  "
        f"(correct {m.n_correct}/{m.n_predicted_non_unknown} pred, "
        f"{m.n_labeled_non_unknown} labeled non-unknown)"
    )


def _fetch_about_text(conn: Any, label: ValidationLabel) -> str | None:
    """Look up the case's CURRENT about_text by the stable (state,
    source_case_id) key, gated to published versions. Sanity-checks that the
    label's verbatim phrases still appear in the narrative (a mismatch means
    the source_case_id is wrong or the narrative drifted -- caller skips)."""
    row = conn.execute(
        text(
            "SELECT c.about_text FROM cold_case.cases c "
            "JOIN etl.dataset_version dv ON dv.dataset_version_id = c.dataset_version_id "
            "AND dv.ingestion_status = 'published' "
            "WHERE c.state = :state AND c.source_case_id = :scid"
        ),
        {"state": label.state, "scid": label.source_case_id},
    ).first()
    if row is None or row.about_text is None:
        return None
    about: str = row.about_text
    for fl in (label.weapon, label.location_type):
        if fl.verbatim_phrase and fl.verbatim_phrase.lower() not in about.lower():
            return None  # phrase no longer present -> wrong/drifted case
    return about


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="rewrite the recorded-responses fixture from this live run",
    )
    args = parser.parse_args(argv)

    model_id = get_pinned_model_id()
    template = load_tier1_prompt_template()
    labels = load_validation_labels()
    client = _RecordingClient(make_llm_client(model_id))

    engine = create_engine(os.environ["DATABASE_URL"])
    weapon_pairs: list[PredictedLabeled] = []
    location_pairs: list[PredictedLabeled] = []
    narratives: dict[str, str] = {}
    unresolved: list[str] = []

    print(f"Validating {len(labels)} cases against pinned model: {model_id}\n", flush=True)
    with engine.connect() as conn:
        for label in labels:
            about_text = _fetch_about_text(conn, label)
            if about_text is None:
                unresolved.append(label.key)
                continue
            client.last_key = label.key
            narratives[label.key] = about_text
            result = extract_case(
                case_id=0,
                about_text=about_text,
                llm_client=client,
                prompt_template=template,
                model_id=model_id,
            )
            weapon_pairs.append(_Pair(result.weapon.value, label.weapon.value))
            location_pairs.append(_Pair(result.location_type.value, label.location_type.value))
            print(
                f"  {label.key}: "
                f"weapon {result.weapon.value!s:>12} (gold {label.weapon.value}) | "
                f"location {result.location_type.value!s:>12} (gold {label.location_type.value})",
                flush=True,
            )
    engine.dispose()

    weapon_m = compute_field_metrics(weapon_pairs)
    location_m = compute_field_metrics(location_pairs)

    print("\n" + "=" * 72)
    print(f"RESULTS - model {model_id}, {len(weapon_pairs)}/{len(labels)} labels scored")
    if unresolved:
        print(f"  unresolved ({len(unresolved)}): {unresolved}")
    print("=" * 72)
    print(_fmt("weapon", weapon_m))
    print(_fmt("location_type", location_m))
    print("=" * 72)
    print(
        "Methodology card value (weapon / location precision): "
        f"{weapon_m.precision * 100:.1f} / {location_m.precision * 100:.1f}"
    )

    if args.record:
        scored = len(weapon_pairs)
        if len(client.records) < scored:
            # Refuse to write a partial fixture: the ship-gate replays
            # records[key] and would KeyError on any case scored but not
            # captured (truly-malformed responses).
            print(
                f"\nNOT writing fixture: captured {len(client.records)} recordings but scored "
                f"{scored} cases. An incomplete fixture would break the validation gate. "
                f"Investigate the uncaptured response(s) first."
            )
            return 1
        # DB-independent fixture: embed the narrative next to the response, keyed
        # by the stable (state:source_case_id). The ship-gate needs no DB.
        payload = {
            key: {"about_text": narratives[key], "response": rec}
            for key, rec in sorted(client.records.items())
        }
        _RECORDED_RESPONSES.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(
            f"\nWrote {len(payload)} recordings (with embedded narratives) -> "
            f"{_RECORDED_RESPONSES.relative_to(_REPO_ROOT)}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
