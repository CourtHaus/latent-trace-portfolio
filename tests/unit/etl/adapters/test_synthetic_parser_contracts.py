"""Invented parser inputs; no agency captures, photographs, or case narratives."""
from pathlib import Path

import pikepdf
import pytest

from casesignal.etl.adapters.cold_case_ar_asp.scrape import (
    INDEX_URL,
    parse_detail_page,
    parse_index_links,
)
from casesignal.etl.adapters.cold_case_co.scrape_detail import parse_detail_page as parse_co
from casesignal.etl.adapters.cold_case_mn_bca.pdf_parser import parse_soc_pdf
from casesignal.etl.adapters.cold_case_ut.scrape_detail import parse_detail_page as parse_ut
from casesignal.etl.adapters.cold_case_ut.scrape_sitemap import parse_sitemap


def test_ar_listing_deduplicates_case_insensitive_slugs() -> None:
    html = f'''<ul class="sidebar-menu"><li><a href="{INDEX_URL}Example-Person/">Example Person</a></li></ul>
    <ul class="wp-block-list"><li><a href="{INDEX_URL}example-person/">Example Person</a></li></ul>'''
    rows = parse_index_links(html, base_url=INDEX_URL)
    assert len(rows) == 1
    assert rows[0].slug == 'example-person'
    assert rows[0].url == INDEX_URL + 'example-person/'


def test_ar_fields_separate_narrative_from_contact() -> None:
    html = '''<p class="wp-block-paragraph"><strong>AGE:</strong> 42</p>
    <p class="wp-block-paragraph"><strong>DATE OF DEATH:</strong> January 1, 2000</p>
    <p class="wp-block-paragraph"><strong>CASE NUMBER:</strong> SYN-001</p>
    <p class="wp-block-paragraph">This invented record tests narrative extraction.</p>
    <p class="wp-block-paragraph is-style-info">Please contact ASP Company A at (202) 555-0100.</p>'''
    result = parse_detail_page(html)
    assert result.age_text == '42'
    assert result.date_label == 'death'
    assert result.case_number == 'SYN-001'
    assert 'invented record' in result.narrative
    assert '555-0100' not in result.narrative
    assert result.contact_phone == '(202) 555-0100'
    assert result.photos == []


def test_co_fields_preserve_unknowns_and_resolve_photo_paths() -> None:
    html = '''<div class="caseDetails"><div class="left"><h2>Example Person</h2></div></div>
    <div class="floatLeft"><p>Case Type: <span>Homicide</span></p>
    <p>Agency Case #: <span>SYN-001</span></p><p>Age: <span></span></p></div>
    <p class="long">An invented narrative used to check the parser boundary.</p>
    <div class="caseHolderPerson"><img src="/coldcase/casefiles/999999/1/large" alt="Synthetic image placeholder"></div>'''
    result = parse_co(html, detail_id=999999, base_url='https://example.test')
    assert result.name == 'Example Person'
    assert result.case_type == 'Homicide'
    assert result.agency_case_id == 'SYN-001'
    assert result.age is None
    assert result.namus_case_id is None
    assert result.photos[0].url == 'https://example.test/coldcase/casefiles/999999/1/large'


def test_ut_sitemap_filters_non_case_links() -> None:
    xml = '''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://bci.utah.gov/coldcases/example-person/</loc><lastmod>2020-01-01</lastmod></url>
    <url><loc>https://bci.utah.gov/contact/</loc></url></urlset>'''
    rows = parse_sitemap(xml)
    assert len(rows) == 1
    assert rows[0].detail_url == 'https://bci.utah.gov/coldcases/example-person/'


def test_ut_detail_keeps_optional_fields_absent() -> None:
    html = '''<section id="divisionContent"><h2>Example Person</h2>
    <ul><li><span class="post-meta-key">Case #:</span> SYN-002</li></ul>
    <p>This deliberately invented narrative is long enough to exercise the paragraph selection rule.</p>
    </section>'''
    result = parse_ut(html, slug='example-person')
    assert result.name == 'Example Person'
    assert result.case_number == 'SYN-002'
    assert result.race is None
    assert result.photos == []


def _write_pdf(path: Path, lines: list[str]) -> None:
    """Create a text-only PDF from invented lines with a built-in PDF font."""
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(612, 792))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                 BaseFont=pikepdf.Name.Helvetica)))
        commands = ['BT /F1 10 Tf 40 740 Td 14 TL']
        for line in lines:
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'({escaped}) Tj T*')
        commands.append('ET')
        page.Contents = pdf.make_stream('\n'.join(commands).encode('ascii'))
        pdf.save(path)


@pytest.mark.parametrize('sex,race,expected', [
    ('Male', 'White', ('Male', 'White')),
    ('Person A male; Person B female', 'Mixed', (None, None)),
])
def test_mn_pdf_extracts_text_and_defers_compound_demographics(
    tmp_path: Path, sex: str, race: str, expected: tuple[str | None, str | None],
) -> None:
    path = tmp_path / 'synthetic.pdf'
    _write_pdf(path, [f'Sex: {sex}', f'Race: {race}',
                     'Details: This is an invented parser example.',
                     'If you have any information please contact Example Unit at 202-555-0100.'])
    result = parse_soc_pdf(path)
    assert result.narrative == 'This is an invented parser example.'
    assert (result.sex, result.race) == expected
    assert result.contact_agency == 'Example Unit'
    assert result.contact_phone == '202-555-0100'


def test_mn_missing_pdf_returns_empty_fields(tmp_path: Path) -> None:
    result = parse_soc_pdf(tmp_path / 'absent.pdf')
    assert result.narrative == ''
    assert result.contact_phone is None
