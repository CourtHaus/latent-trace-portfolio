"""Pin the correlation config surface — methodology copy cites these names."""

from __future__ import annotations

from casesignal.correlation import config


def test_gate_unchanged() -> None:
    assert config.CORRELATION_GEO_MILES == 50
    assert config.CORRELATION_TIME_YEARS == 20
    assert config.CORRELATION_TOP_N == 5


def test_rarity_scoring_constants_exist_and_are_sane() -> None:
    assert config.CORRELATION_SMOOTHING_ALPHA == 1.0
    assert 0 < config.CORRELATION_DISTANCE_HALF_LIFE_MILES <= config.CORRELATION_GEO_MILES
    assert 0 < config.CORRELATION_TIME_HALF_LIFE_YEARS <= config.CORRELATION_TIME_YEARS
    assert (
        0
        <= config.CORRELATION_AGE_KERNEL_FULL_YEARS
        < config.CORRELATION_AGE_KERNEL_ZERO_YEARS
    )
    assert config.CORRELATION_AGE_CLOSE_YEARS > 0
    assert config.CORRELATION_MIN_DIMENSIONS == 2
    assert config.CORRELATION_SCORE_SCALE == 10.0
    assert 0 < config.CORRELATION_SCORE_FLOOR < config.CORRELATION_SCORE_SCALE
    assert config.CORRELATION_BASE_RATES_TTL_SECONDS >= 60


def test_flat_weights_are_gone() -> None:
    for name in (
        "CORRELATION_WEIGHT_WEAPON",
        "CORRELATION_WEIGHT_LOCATION_TYPE",
        "CORRELATION_WEIGHT_VICTIM_GENDER",
        "CORRELATION_WEIGHT_VICTIM_RACE",
        "CORRELATION_WEIGHT_VICTIM_AGE_BAND",
        "CORRELATION_AGE_BAND_YEARS",
        "CORRELATION_SCORE_MAX",
    ):
        assert not hasattr(config, name)
