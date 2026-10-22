from casesignal.extraction.cold_case.prompt_loader import (
    compute_prompt_hash,
    load_tier2_prompt_template,
    load_tier2_v2_prompt_template,
    load_tier2_v3_prompt_template,
)


def test_v3_loader_returns_a_template_string() -> None:
    template = load_tier2_v3_prompt_template()
    assert isinstance(template, str)
    assert "{about_text}" in template


def test_v3_has_no_race_field() -> None:
    """v3 explicitly omits victim_race — see feedback-no-llm-race-inference.

    If a future change reintroduces race extraction in this prompt, this
    assertion catches it before the prompt ships.
    """
    template = load_tier2_v3_prompt_template()
    assert "victim_race" not in template
    assert "race" not in template.lower()


def test_v3_keeps_multi_victim_gender_guardrail() -> None:
    """v3 preserves v2's multi-victim gender-disambiguation paragraph."""
    template = load_tier2_v3_prompt_template()
    assert "multi-victim" in template.lower() or "multi-person" in template.lower()


def test_v3_hash_differs_from_v1_and_v2() -> None:
    v1 = compute_prompt_hash(load_tier2_prompt_template())
    v2 = compute_prompt_hash(load_tier2_v2_prompt_template())
    v3 = compute_prompt_hash(load_tier2_v3_prompt_template())
    assert v1 != v3, "v3 must hash differently from v1"
    assert v2 != v3, "v3 must hash differently from v2 so v2 race rows stay distinguishable"
