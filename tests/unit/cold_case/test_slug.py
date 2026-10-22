from __future__ import annotations

import pytest

from casesignal.cold_case.slug import build_case_slug


class TestBuildCaseSlug:
    def test_full_composition(self) -> None:
        assert build_case_slug("Jane Doe", "Richmond", "VA", 1998) == "jane-doe-richmond-va-1998"

    def test_null_city_drops_segment(self) -> None:
        assert build_case_slug("Jane Doe", None, "VA", 1998) == "jane-doe-va-1998"

    def test_null_year_drops_segment(self) -> None:
        assert build_case_slug("Jane Doe", "Richmond", "VA", None) == "jane-doe-richmond-va"

    def test_both_null(self) -> None:
        assert build_case_slug("Jane Doe", None, "VA", None) == "jane-doe-va"

    def test_punctuation_collapsed(self) -> None:
        assert (
            build_case_slug("Smith, John A.", "Norfolk", "VA", 2004)
            == "smith-john-a-norfolk-va-2004"
        )

    def test_unicode_transliterates(self) -> None:
        # python-slugify transliterates accented Latin → ASCII.
        assert (
            build_case_slug("José Martínez", "El Paso", "TX", 2010)
            == "jose-martinez-el-paso-tx-2010"
        )

    def test_length_clamped_to_80_chars(self) -> None:
        long_name = "A" * 200
        result = build_case_slug(long_name, "Richmond", "VA", 1998)
        assert len(result) <= 80

    def test_long_case_name_preserves_suffix_tokens(self) -> None:
        # Regression: prior implementation truncated the trailing state/year
        # off long slugs. The state token is the most disambiguating short
        # piece and must survive truncation.
        long_name = "Hampton Police Division Kenneth Bradford Jackson 2703 W Weaver Road"
        result = build_case_slug(long_name, "Hampton", "VA", 2005)
        assert len(result) <= 80
        assert result.endswith("-va-2005")

    def test_state_lowercased(self) -> None:
        # State is always 2 uppercase chars in the DB; output should be lowercase.
        assert "va" in build_case_slug("Jane Doe", "Richmond", "VA", 1998)
        assert "VA" not in build_case_slug("Jane Doe", "Richmond", "VA", 1998)

    def test_unidentified_victim_naming(self) -> None:
        # Common case: the case_name itself carries the "Unidentified ..." phrasing.
        assert build_case_slug("Unidentified Female", None, "VA", None) == "unidentified-female-va"

    def test_rejects_whitespace_only_case_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            build_case_slug("   ", "Richmond", "VA", 1998)

    def test_rejects_empty_case_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            build_case_slug("", "Richmond", "VA", 1998)
