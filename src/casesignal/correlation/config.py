"""Tunable constants for the cold-case correlation engine (Phase A,
rarity-weighted). Single source of truth — the methodology endpoint and page
cite these values by name to prevent drift between code and documentation.

Spec: docs/engineering-decisions.md
"""

from __future__ import annotations

# Candidate-pool gate (unchanged from C2).
CORRELATION_GEO_MILES = 50
CORRELATION_TIME_YEARS = 20
CORRELATION_TOP_N = 5

# Rarity weighting: Laplace smoothing for corpus frequencies.
CORRELATION_SMOOTHING_ALPHA = 1.0

# Proximity discount half-lives: score multiplier is
# 2**(-distance/D_HALF) * 2**(-years/T_HALF). Provisional values, tuned once
# against the graded-pairs report (see the Phase A plan, calibration task).
CORRELATION_DISTANCE_HALF_LIFE_MILES = 20.0
CORRELATION_TIME_HALF_LIFE_YEARS = 10.0

# Graded age similarity: full weight at |delta| <= FULL, linear taper to zero
# at |delta| >= ZERO. The weight constant is the surprisal of two random
# victims being within CLOSE years (computed from the corpus age histogram).
CORRELATION_AGE_KERNEL_FULL_YEARS = 2
CORRELATION_AGE_KERNEL_ZERO_YEARS = 12
CORRELATION_AGE_CLOSE_YEARS = 5

# Lead rules. The floor is in normalized (0-10) units and is CALIBRATED
# against corpus lead volume (target: within ~25% of the pre-Phase-A
# (case, lead) pair count). Calibration date and method: see methodology.
CORRELATION_MIN_DIMENSIONS = 2
# Calibrated 2026-06-13 against the churn report (tools/correlation_grading.py,
# docs/engineering-decisions.md): the pre-Phase-A flat
# formula shipped 28,056 (case, lead) pairs corpus-wide. At this floor the
# rarity-weighted engine yields 25,233 pairs (90% of old volume, within the
# agreed +/-25% band) while ranking them by surprisal. One step stricter than
# the closest-to-old floor (0.25 -> 29,062), per "fewer, better leads".
CORRELATION_SCORE_FLOOR = 0.5
CORRELATION_SCORE_SCALE = 10.0

# Base-rate cache refresh (frequencies recompute at most this often).
CORRELATION_BASE_RATES_TTL_SECONDS = 3600
