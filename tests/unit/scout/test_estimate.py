from casesignal.scout.estimate import (
    estimate_count_from_listing,
    estimate_plottability,
)
from casesignal.scout.models import Confidence, FieldSpec, Location


def test_api_count_is_exact() -> None:
    cc = estimate_count_from_listing(html="", api_count=87)
    assert cc.value == 87 and cc.confidence == Confidence.EXACT


def test_stated_total_is_exact() -> None:
    cc = estimate_count_from_listing(html="<p>Showing 1 to 25 of 312 results</p>")
    assert cc.value == 312 and cc.confidence == Confidence.EXACT


def test_visible_rows_when_no_total() -> None:
    html = '<div class="case"></div>' * 25
    cc = estimate_count_from_listing(html=html)
    assert cc.value == 25 and cc.confidence == Confidence.VISIBLE


def test_page_of_n_footer_does_not_false_positive_as_total() -> None:
    # "Page 1 of 13" is a pagination footer, not a results total, and carries no
    # pagination markers here, so the ladder must fall through to VISIBLE (8),
    # never stamping the page count (13) at the EXACT rung.
    html = "<p>Page 1 of 13</p>" + '<div class="case"></div>' * 8
    cc = estimate_count_from_listing(html=html)
    assert cc.value == 8 and cc.confidence == Confidence.VISIBLE


def test_pagination_is_probed() -> None:
    cc = estimate_count_from_listing(html='<a rel="next" href="?page=2">Next</a>')
    assert cc.value is None and cc.confidence == Confidence.PROBED


def test_plottability_structured_county_is_full() -> None:
    fields = {"county": FieldSpec(present=True, location=Location.STRUCTURED)}
    est, basis = estimate_plottability(fields)
    assert est == 1.0 and "county" in basis.lower()


def test_plottability_narrative_only_is_low() -> None:
    fields = {"county": FieldSpec(present=True, location=Location.NARRATIVE)}
    est, _ = estimate_plottability(fields)
    assert est == 0.5
