"""Tests for DC MPDC narrative honorific → gender inference.

Per feedback_demographic_inference_rules memory: gender from
narrative honorifics is acceptable (source-author wrote them).
Gender from name alone is NEVER acceptable.
"""

from __future__ import annotations


def test_mr_honorific_returns_M() -> None:
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert (
        infer_gender_from_honorific(
            "On January 1, 2000 at approximately 1:00 pm, Mr. Alex Exampleton was shot and killed."
        )
        == "M"
    )


def test_mrs_honorific_returns_F() -> None:
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert infer_gender_from_honorific("Mrs. Jane Doe was killed.") == "F"


def test_ms_honorific_returns_F() -> None:
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert infer_gender_from_honorific("Ms. Maria Lopez was killed.") == "F"


def test_miss_honorific_returns_F() -> None:
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert infer_gender_from_honorific("Miss Anna Smith was killed.") == "F"


def test_mx_honorific_returns_None() -> None:
    """Mx. is gender-neutral; we don't fabricate M/F."""
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert infer_gender_from_honorific("Mx. Robin Doe was killed.") is None


def test_no_honorific_returns_None() -> None:
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert (
        infer_gender_from_honorific("On Tuesday, John Doe was found dead at the location.") is None
    )


def test_honorific_case_insensitive() -> None:
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert infer_gender_from_honorific("MR. JANE DOE was killed.") == "M"
    assert infer_gender_from_honorific("mrs. lower case") == "F"


def test_honorific_with_no_period_works() -> None:
    """Some sources may omit the period (Mr instead of Mr.)."""
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert infer_gender_from_honorific("Mr Smith was killed.") == "M"


def test_first_honorific_wins_for_mixed() -> None:
    """If a narrative mentions multiple people with honorifics, return
    the first match (the victim is named first by convention)."""
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert (
        infer_gender_from_honorific(
            "Mr. Alex Exampleton was killed. Mrs. Smith witnessed the crime."
        )
        == "M"
    )


def test_empty_string_returns_None() -> None:
    from casesignal.etl.adapters.cold_case_dc_mpdc.honorific_regex import (
        infer_gender_from_honorific,
    )

    assert infer_gender_from_honorific("") is None
