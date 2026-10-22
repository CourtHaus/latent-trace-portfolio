from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str

    model_config = ConfigDict(extra="forbid")


class DimensionWeightExample(BaseModel):
    """A live worked example for the methodology page: the bits earned by a
    match on this value, from the current corpus base rates. `rarity` labels
    whether this is the most common or the rarest value in its dimension, so
    the page can teach the common-vs-rare contrast without the reader having
    to interpret the raw bits figure."""

    dimension: str
    value: str
    bits: float
    rarity: Literal["common", "rare"]

    model_config = ConfigDict(extra="forbid")


class CorrelationConfigResponse(BaseModel):
    """The correlation engine's tunable constants + live derived values — the
    single source the methodology page's scoring section renders from."""

    geo_miles: int
    time_years: int
    top_n: int
    smoothing_alpha: float
    distance_half_life_miles: float
    time_half_life_years: float
    age_kernel_full_years: int
    age_kernel_zero_years: int
    age_close_years: int
    min_dimensions: int
    score_floor: float
    score_scale: float
    raw_max_bits: float
    age_close_weight_bits: float
    example_weights: list[DimensionWeightExample]

    model_config = ConfigDict(extra="forbid")
