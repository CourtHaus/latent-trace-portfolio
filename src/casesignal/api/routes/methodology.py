"""Read-only methodology endpoints — expose engine constants so the
public methodology page renders from the same source the engine runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from casesignal.api.dependencies.db import get_db_session
from casesignal.api.schemas.common import CorrelationConfigResponse, DimensionWeightExample
from casesignal.correlation import config
from casesignal.correlation.base_rates import get_base_rates
from casesignal.correlation.scoring import raw_max

router = APIRouter(prefix="/methodology", tags=["methodology"])


@router.get("/correlation-weights", response_model=CorrelationConfigResponse)
def get_correlation_weights(
    session: Session = Depends(get_db_session),
) -> CorrelationConfigResponse:
    """Return the correlation engine's tunable constants + live derived values
    from the current corpus so the methodology page cannot drift from them."""
    rates = get_base_rates(session)

    examples: list[DimensionWeightExample] = []
    dim_maps = [
        ("weapon", rates.weapon),
        ("location_type", rates.location_type),
        ("victim_gender", rates.victim_gender),
        ("victim_race", rates.victim_race),
    ]
    for dim_name, weights in dim_maps:
        if not weights:
            continue
        # Lightest weight = most common value (low surprisal); heaviest =
        # rarest. Emit both so the page can show the spread; the `rarity` tag
        # lets a lay reader read the contrast without parsing the bits.
        lightest_val = min(weights, key=lambda v: weights[v])
        heaviest_val = max(weights, key=lambda v: weights[v])
        examples.append(
            DimensionWeightExample(
                dimension=dim_name,
                value=lightest_val,
                bits=round(weights[lightest_val], 2),
                rarity="common",
            )
        )
        if heaviest_val != lightest_val:
            examples.append(
                DimensionWeightExample(
                    dimension=dim_name,
                    value=heaviest_val,
                    bits=round(weights[heaviest_val], 2),
                    rarity="rare",
                )
            )

    return CorrelationConfigResponse(
        geo_miles=config.CORRELATION_GEO_MILES,
        time_years=config.CORRELATION_TIME_YEARS,
        top_n=config.CORRELATION_TOP_N,
        smoothing_alpha=config.CORRELATION_SMOOTHING_ALPHA,
        distance_half_life_miles=config.CORRELATION_DISTANCE_HALF_LIFE_MILES,
        time_half_life_years=config.CORRELATION_TIME_HALF_LIFE_YEARS,
        age_kernel_full_years=config.CORRELATION_AGE_KERNEL_FULL_YEARS,
        age_kernel_zero_years=config.CORRELATION_AGE_KERNEL_ZERO_YEARS,
        age_close_years=config.CORRELATION_AGE_CLOSE_YEARS,
        min_dimensions=config.CORRELATION_MIN_DIMENSIONS,
        score_floor=config.CORRELATION_SCORE_FLOOR,
        score_scale=config.CORRELATION_SCORE_SCALE,
        raw_max_bits=round(raw_max(rates), 2),
        age_close_weight_bits=round(rates.age_close_weight, 2),
        example_weights=examples,
    )
