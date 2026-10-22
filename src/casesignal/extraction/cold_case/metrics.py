"""Precision/recall metrics for the validation-set ship gate.

See spec decision #25 for the exact definitions. Both denominators exclude
labels whose ground truth is "unknown" — we're measuring the extractor's
ability to find weapons and locations when the narrative contains them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class PredictedLabeled(Protocol):
    predicted: str | None
    labeled: str


@dataclass(frozen=True)
class FieldMetrics:
    precision: float
    recall: float
    n_predicted_non_unknown: int
    n_labeled_non_unknown: int
    n_correct: int


def compute_field_metrics(pairs: Iterable[PredictedLabeled]) -> FieldMetrics:
    """Precision + recall over a collection of (predicted, labeled) pairs."""
    pairs = list(pairs)

    # Filter to scoreable labels: labels where ground truth is non-unknown.
    scoreable = [p for p in pairs if p.labeled != "unknown"]
    n_labeled_non_unknown = len(scoreable)

    # Recall: fraction of non-unknown labels where prediction equals label
    # (and prediction is non-unknown and non-None).
    n_correct = sum(
        1
        for p in scoreable
        if p.predicted is not None and p.predicted != "unknown" and p.predicted == p.labeled
    )
    recall = n_correct / n_labeled_non_unknown if n_labeled_non_unknown > 0 else 1.0

    # Precision: of non-unknown predictions (on scoreable pairs), % matching.
    non_unknown_preds = [p for p in scoreable if p.predicted not in (None, "unknown")]
    n_predicted_non_unknown = len(non_unknown_preds)
    if n_predicted_non_unknown == 0:
        precision = 1.0  # vacuous; no positive predictions to judge
    else:
        precision = (
            sum(1 for p in non_unknown_preds if p.predicted == p.labeled) / n_predicted_non_unknown
        )

    return FieldMetrics(
        precision=precision,
        recall=recall,
        n_predicted_non_unknown=n_predicted_non_unknown,
        n_labeled_non_unknown=n_labeled_non_unknown,
        n_correct=n_correct,
    )
