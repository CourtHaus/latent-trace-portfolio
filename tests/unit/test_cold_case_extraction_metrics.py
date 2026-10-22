"""Unit tests for precision/recall computation.

Definitions (per the spec):
  precision = of the extractor's non-unknown predictions, % matching the label's non-unknown value.
  recall    = of labeled non-unknown values, % where the extractor also produced a non-unknown value AND that value matched.
  Both metrics ignore labels where the ground truth is "unknown".
"""

from __future__ import annotations

from dataclasses import dataclass

from casesignal.extraction.cold_case.metrics import (
    PredictedLabeled,
    compute_field_metrics,
)


@dataclass(frozen=True)
class Pair(PredictedLabeled):
    predicted: str | None
    labeled: str


def test_all_correct_non_unknown() -> None:
    pairs = [Pair("firearm", "firearm"), Pair("knife", "knife")]
    m = compute_field_metrics(pairs)
    assert m.precision == 1.0
    assert m.recall == 1.0


def test_all_wrong() -> None:
    pairs = [Pair("firearm", "knife"), Pair("knife", "firearm")]
    m = compute_field_metrics(pairs)
    assert m.precision == 0.0
    assert m.recall == 0.0


def test_unknown_in_label_ignored() -> None:
    # Labeled unknown → not counted toward precision or recall denominators.
    pairs = [Pair("firearm", "firearm"), Pair("unknown", "unknown"), Pair("knife", "unknown")]
    m = compute_field_metrics(pairs)
    # Only the first pair is scoreable; it was correct.
    assert m.precision == 1.0
    assert m.recall == 1.0


def test_degenerate_unknown_extractor_has_low_recall() -> None:
    # Extractor returns "unknown" for everything; labels are non-unknown.
    # Precision denominator = 0 (no non-unknown predictions) → defined as 1.0 vacuously — OK,
    # because recall catches the degenerate case.
    pairs = [Pair("unknown", "firearm"), Pair("unknown", "knife")]
    m = compute_field_metrics(pairs)
    assert m.precision == 1.0  # vacuous; no positive predictions to be wrong about
    assert m.recall == 0.0  # zero labeled non-unknowns recovered


def test_extractor_failed_value_none() -> None:
    # value=None (API failure) → treated as "didn't predict anything for this case".
    # Counts toward recall denominator (label was non-unknown), not recovered.
    pairs = [Pair(None, "firearm"), Pair("firearm", "firearm")]
    m = compute_field_metrics(pairs)
    assert m.precision == 1.0  # 1/1 non-unknown predictions correct
    assert m.recall == 0.5  # 1/2 non-unknown labels recovered


def test_partial_correctness() -> None:
    # 3 correct, 1 wrong, 1 unknown-pred on non-unknown label, out of 5 non-unknown labels.
    pairs = [
        Pair("firearm", "firearm"),
        Pair("knife", "knife"),
        Pair("firearm", "firearm"),
        Pair("firearm", "knife"),  # wrong prediction
        Pair("unknown", "blunt"),  # didn't predict
    ]
    m = compute_field_metrics(pairs)
    # Precision: 4 non-unknown predictions; 3 correct → 0.75
    assert m.precision == 0.75
    # Recall: 5 non-unknown labels; 3 recovered → 0.6
    assert m.recall == 0.6
