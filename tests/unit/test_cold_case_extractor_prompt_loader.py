"""Unit tests for prompt loader — template reading + hash computation."""

from __future__ import annotations

from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    load_tier1_prompt_template,
    load_tier2_v4_prompt_template,
    render_prompt,
)


def test_load_tier1_prompt_template_contains_schema() -> None:
    template = load_tier1_prompt_template()
    assert "weapon" in template
    assert "location_type" in template
    assert "{about_text}" in template


def test_active_tier1_prompt_is_v2_with_geolocation_fix() -> None:
    """The active Tier-1 prompt must be v2: a street address used to geolocate
    an outdoor body must not be read as `residence`. Two marker phrases unique
    to v2's location-tree edit (Step 2 + Step 4)."""
    template = load_tier1_prompt_template()
    assert "GEOLOCATION, not a scene type" in template
    assert "the scene is the outdoor feature" in template


def test_compute_prompt_hash_is_stable_across_calls() -> None:
    h1 = compute_prompt_hash(load_tier1_prompt_template())
    h2 = compute_prompt_hash(load_tier1_prompt_template())
    assert h1 == h2
    # sha256 hex is 64 chars
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_compute_prompt_hash_changes_on_edit() -> None:
    h1 = compute_prompt_hash("prompt v1")
    h2 = compute_prompt_hash("prompt v1 edited")
    assert h1 != h2


def test_render_prompt_interpolates_about_text() -> None:
    rendered = render_prompt("template {about_text} after", "narrative here")
    assert rendered == "template narrative here after"


def test_load_tier2_v4_prompt_template_contains_victims_and_placeholder() -> None:
    template = load_tier2_v4_prompt_template()
    assert template  # non-empty
    assert "victims" in template
    assert "{about_text}" in template


def test_render_prompt_preserves_literal_braces_around_schema() -> None:
    # The template contains { and } in the schema description; render must
    # only substitute {about_text} and leave other braces intact.
    template = load_tier1_prompt_template()
    rendered = render_prompt(template, "TEST_ABOUT_TEXT")
    assert "TEST_ABOUT_TEXT" in rendered
    # schema-shape braces preserved
    assert '"weapon"' in rendered or "weapon:" in rendered
