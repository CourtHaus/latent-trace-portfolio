"""Unit tests for the deterministic offset resolver.

Given about_text + LLM-returned verbatim phrase, resolve to (start, end, low_confidence):
  1. strict exact substring match → offsets + low_confidence=False
  2. case-insensitive + whitespace-collapsed fallback → offsets + low_confidence=False
     (but the RETURNED offsets index into the original text, not the normalized text)
  3. no match → (0, 0, True)
"""

from __future__ import annotations

from casesignal.extraction.cold_case.offsets import resolve_offsets


class TestStrictMatch:
    def test_exact_match_at_start(self) -> None:
        text = "shot to death in a shed"
        start, end, low = resolve_offsets(text, "shot to death")
        assert (start, end, low) == (0, 13, False)
        assert text[start:end] == "shot to death"

    def test_exact_match_mid_string(self) -> None:
        text = "The victim was shot to death at home."
        start, end, low = resolve_offsets(text, "shot to death")
        assert text[start:end] == "shot to death"
        assert low is False

    def test_first_occurrence_wins_on_duplicates(self) -> None:
        text = "shot multiple times. Later, shot in the leg."
        start, end, low = resolve_offsets(text, "shot")
        assert start == 0  # first occurrence
        assert low is False

    def test_phrase_at_end(self) -> None:
        text = "apparent stab wounds"
        start, end, low = resolve_offsets(text, "stab wounds")
        assert text[start:end] == "stab wounds"
        assert low is False


class TestLenientMatch:
    def test_case_insensitive_match(self) -> None:
        text = "The victim was Shot To Death at home."
        start, end, low = resolve_offsets(text, "shot to death")
        assert text[start:end].lower() == "shot to death"
        assert low is False

    def test_whitespace_collapsed_match(self) -> None:
        text = "found in a shed\n\nin the back yard"
        start, end, low = resolve_offsets(text, "in a shed in the back yard")
        # The returned offsets span the original-text occurrence including the newlines.
        assert text[start:end].replace("\n", " ").replace("  ", " ") == "in a shed in the back yard"
        assert low is False

    def test_tab_and_multiple_spaces_normalized(self) -> None:
        text = "stabbed\t\twith a\t\tknife"
        start, end, low = resolve_offsets(text, "stabbed with a knife")
        assert low is False
        # Offsets point into the original text with tabs.
        assert "stabbed" in text[start:end]
        assert "knife" in text[start:end]


class TestDrops:
    def test_phrase_not_in_text_drops(self) -> None:
        text = "The victim was shot."
        start, end, low = resolve_offsets(text, "stabbed multiple times")
        assert (start, end, low) == (0, 0, True)

    def test_paraphrase_not_rescued_by_edit_distance(self) -> None:
        text = "The victim was shot to death."
        # LLM paraphrase — no verbatim match.
        start, end, low = resolve_offsets(text, "shot fatally")
        assert low is True

    def test_empty_phrase_drops(self) -> None:
        start, end, low = resolve_offsets("any text", "")
        assert low is True

    def test_none_phrase_drops(self) -> None:
        # The extractor passes None when the LLM classified unknown; the resolver
        # should handle this without exception.
        start, end, low = resolve_offsets("any text", None)
        assert low is True


class TestEdgeCases:
    def test_phrase_longer_than_text(self) -> None:
        start, end, low = resolve_offsets("short", "a much longer phrase than the text")
        assert low is True

    def test_empty_about_text_drops(self) -> None:
        start, end, low = resolve_offsets("", "anything")
        assert low is True

    def test_unicode_preserved(self) -> None:
        text = "the victim's name was María"
        start, end, low = resolve_offsets(text, "María")
        assert text[start:end] == "María"
        assert low is False
