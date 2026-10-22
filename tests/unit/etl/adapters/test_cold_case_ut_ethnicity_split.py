from __future__ import annotations

from typing import Any

import pytest

from casesignal.etl.adapters.cold_case_ut.ethnicity import classify


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Hispanic", (None, "Hispanic")),
        ("hispanic", (None, "hispanic")),
        ("Latino", (None, "Latino")),
        ("Latina", (None, "Latina")),
        ("White/Caucasian", ("White/Caucasian", None)),
        ("Black", ("Black", None)),
        ("Asian", ("Asian", None)),
        ("Native American", ("Native American", None)),
        ("", (None, None)),
        (None, (None, None)),
        ("  Hispanic  ", (None, "Hispanic")),  # strip preserved value
    ],
)
def test_classify(raw: Any, expected: Any) -> None:
    assert classify(raw) == expected
