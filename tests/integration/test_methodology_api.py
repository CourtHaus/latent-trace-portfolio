"""Integration test for the methodology read endpoints."""

from __future__ import annotations

import os
from typing import Any

import pytest

from tests.integration._seed import CaseSpec, ExtractionSpec, SeedFn, VictimSpec

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


def _client() -> Any:
    from fastapi.testclient import TestClient

    from casesignal.api.app import create_app

    return TestClient(create_app())


def _weights_case(suffix: str, *, weapon: str, location: str, gender: str, race: str, age: int) -> CaseSpec:
    return CaseSpec(
        source_case_id=f"MW-{suffix}",
        case_name=f"Methodology Weights Case {suffix}",
        state="ZZ",
        victims=[
            VictimSpec(
                first_name="Jane",
                last_name=f"Doe{suffix}",
                gender=gender,
                race=race,
                age_text=str(age),
            )
        ],
        extractions=[ExtractionSpec(prompt_tier=1, weapon=weapon, location_type=location)],
    )


def test_correlation_config_endpoint(seed: SeedFn) -> None:
    """200, constants match config, derived values are sane, examples non-empty."""
    from casesignal.correlation import config

    # The endpoint derives raw_max_bits / example_weights from the live
    # published corpus. Seed a small skewed corpus (2:1 per dimension) so the
    # test is self-sufficient on an empty DB: every dimension gets a common
    # AND a rare value with distinct positive bits.
    seed(
        "METHODOLOGY_TEST_WEIGHTS",
        [
            _weights_case("a", weapon="firearm", location="residence", gender="F", race="White", age=30),
            _weights_case("b", weapon="firearm", location="residence", gender="F", race="White", age=32),
            _weights_case("c", weapon="knife", location="vehicle", gender="M", race="Black", age=60),
        ],
    )

    resp = _client().get("/api/v1/methodology/correlation-weights")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Constants mirror config
    assert body["geo_miles"] == config.CORRELATION_GEO_MILES
    assert body["time_years"] == config.CORRELATION_TIME_YEARS
    assert body["top_n"] == config.CORRELATION_TOP_N
    assert body["score_scale"] == config.CORRELATION_SCORE_SCALE
    assert body["min_dimensions"] == config.CORRELATION_MIN_DIMENSIONS
    assert body["score_floor"] == config.CORRELATION_SCORE_FLOOR

    # Exact expected values
    assert body["score_scale"] == 10.0
    assert body["min_dimensions"] == 2

    # Live derived values
    assert body["raw_max_bits"] > 0, "raw_max_bits should be positive when corpus has data"

    # example_weights: non-empty, all bits positive, every entry rarity-tagged,
    # per-dimension common-before-rare in ascending bits.
    examples = body["example_weights"]
    assert len(examples) > 0, "expected at least one example weight entry"
    for ex in examples:
        assert ex["bits"] > 0, f"example bits not positive: {ex}"
        assert ex["rarity"] in ("common", "rare"), f"missing rarity tag: {ex}"

    # Per-dimension: the 'common' entry must be lighter than the 'rare' entry.
    dims: dict[str, list[tuple[float, str]]] = {}
    for ex in examples:
        dims.setdefault(ex["dimension"], []).append((ex["bits"], ex["rarity"]))
    for dim, entries in dims.items():
        bits_list = [b for b, _ in entries]
        assert bits_list == sorted(bits_list), (
            f"dimension '{dim}' examples not in lightest->heaviest order: {bits_list}"
        )
        if len(entries) == 2:
            assert entries[0][1] == "common" and entries[1][1] == "rare", (
                f"dimension '{dim}' rarity tags not common->rare: {entries}"
            )
