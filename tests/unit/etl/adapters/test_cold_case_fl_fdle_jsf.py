"""FDLE JSF scraper parsing and payload helpers."""

from __future__ import annotations

from casesignal.etl.adapters.cold_case_fl_fdle.jsf import (
    build_row_select_payload,
    build_search_payload,
    parse_captcha_answer,
    parse_case_detail,
    parse_partial_redirect,
    parse_results,
    parse_view_state,
)
from casesignal.etl.adapters.cold_case_fl_fdle.register import canonical_entries_hash
from casesignal.etl.adapters.cold_case_fl_fdle.transform import (
    _normalize_case_type,
    _normalize_fl_date,
    _split_fdle_name,
)
from casesignal.etl.runners.run_pipeline import build_adapter_registry
from casesignal.etl.services.source_catalog import SourceCatalog

SEARCH_HTML = """
<form id="searchForm">
  <input id="searchForm:captchaInput" name="searchForm:captchaInput"
         title="Enter Captcha Text 4782" />
  <input type="hidden" name="javax.faces.ViewState"
         id="j_id1:javax.faces.ViewState:3" value="STATE123" />
</form>
"""


RESULTS_XML = """
<partial-response><changes><update id="searchForm"><![CDATA[
<div id="searchForm:resultsTable" class="ui-datatable">
  <tbody id="searchForm:resultsTable_data">
    <tr data-ri="0" data-rk="1376" class="ui-datatable-selectable">
      <td><img src="/unsolvedcases/javax.faces.resource/dynamiccontent.properties.jsf?SUP_REL_OBJ_FILEID=422&amp;pfdrid_c=true" /></td>
      <td><span id="searchForm:resultsTable:0:nameTable">Sampler, Robin Middle</span></td>
      <td><span id="searchForm:resultsTable:0:dobTable">07-08-1963</span></td>
      <td><span id="searchForm:resultsTable:0:raceTable">BLACK or AFRICAN AMERICAN</span></td>
      <td><span id="searchForm:resultsTable:0:genderTable">MALE</span></td>
      <td><label class="Fs14">FDLE - Tallahassee</label></td>
      <td><label class="Fs14">11-02-2012</label></td>
    </tr>
  </tbody>
</div>
<script>PrimeFaces.cw("DataTable","resultsWid",{id:"searchForm:resultsTable",paginator:{rows:10,rowCount:587,page:0}});</script>
]]></update><update id="j_id1:javax.faces.ViewState:0"><![CDATA[STATE456]]></update></changes></partial-response>
"""

PAGINATION_XML = RESULTS_XML.replace(
    '<update id="searchForm">',
    '<update id="searchForm:resultsTable">',
)

PAGINATION_ROWS_XML = """
<partial-response><changes><update id="searchForm:resultsTable"><![CDATA[
<tr data-ri="10" data-rk="1427" class="ui-datatable-selectable">
  <td><img src="/unsolvedcases/javax.faces.resource/images/Multiple_Victims_Stock_Photo.png.jsf?ln=sentinel-layout" /></td>
  <td><span id="searchForm:resultsTable:10:nameTable">UNK-BF, Trout Lake (Alachua CSO)</span></td>
  <td><span id="searchForm:resultsTable:10:dobTable"></span></td>
  <td><span id="searchForm:resultsTable:10:raceTable">BLACK or AFRICAN AMERICAN</span></td>
  <td><span id="searchForm:resultsTable:10:genderTable">FEMALE</span></td>
  <td><label class="Fs14">Alachua County Sheriffs Office</label></td>
  <td><label class="Fs14">03-21-2001</label></td>
</tr>
]]></update><update id="j_id1:javax.faces.ViewState:0"><![CDATA[STATE789]]></update></changes></partial-response>
"""


DETAIL_HTML = """
<html><head>
  <meta property="og:image" content="http://web.fdle.state.fl.us/unsolvedcases/imageLoader?f=422" />
</head><body>
<form id="caseDetailsForm">
  <label class="Fs24">Case Information:</label>
  <label class="Fs18 ">Robin "Pig" Sampler Death Investigation (11/2012)</label>
  <label class="Fs14 FontBold">Case Type: </label><label class="Fs14">Homicide</label>
  <label class="Fs14 FontBold">Address: </label><label class="Fs14">101 Example Lane Quincy FL</label>
  <label class="Fs14 FontBold">Incident Date: </label><label class="Fs14">11-02-2012</label>
  <label style="font-weight:bold !important;" class="Fs14">About this case:</label>
  <div><label class="Fs14">On Friday, November 2, 2012 FDLE opened the investigation.</label></div>
  <label class="Fs24">Subject Information:</label>
  <label style="font-weight:bold !important;" class="Fs18 ">Sampler, Robin Middle</label>
  <label class="Fs14 FontBold">Gender: </label><label class="Fs14">MALE</label>
  <label class="Fs14 FontBold">Race: </label><label class="Fs14">BLACK or AFRICAN AMERICAN</label>
  <label class="Fs14 FontBold">Address: </label><label class="Fs14">101 Example Lane, Quincy, FL, 32351</label>
  <label class="Fs24">Reporting Agency Information:</label>
  <label class="Fs14 FontBold">Name: </label><label class="Fs14">FDLE - Tallahassee</label>
  <label class="Fs14 FontBold">Address: </label><label class="Fs14">202 Sample Avenue</label>
  <label class="Fs14 FontBold">Contact Phone: </label><label class="Fs14">2025550100</label>
  <img src="/unsolvedcases/javax.faces.resource/dynamiccontent.properties.jsf?SUB_REL_OBJ_FILEID=1616&amp;pfdrid_c=true" />
</form>
</body></html>
"""

DETAIL_HTML_WITH_EMPTY_LABEL = DETAIL_HTML.replace(
    '<label style="font-weight:bold !important;" class="Fs14">About this case:</label>',
    '<label class="Fs14">   </label><label style="font-weight:bold !important;" class="Fs14">About this case:</label>',
)


def test_parse_search_gate_values() -> None:
    assert parse_captcha_answer(SEARCH_HTML) == "4782"
    assert parse_view_state(SEARCH_HTML) == "STATE123"


def test_build_primefaces_search_payload() -> None:
    payload = build_search_payload(
        view_state="STATE123",
        captcha_answer="4782",
        case_type="H",
    )

    assert payload["javax.faces.partial.ajax"] == "true"
    assert payload["javax.faces.source"] == "searchForm:searchBtn"
    assert payload["searchForm:caseType_input"] == "H"
    assert payload["searchForm:captchaInput"] == "4782"
    assert payload["javax.faces.ViewState"] == "STATE123"


def test_parse_results_table_uses_primefaces_row_keys() -> None:
    page = parse_results(RESULTS_XML)

    assert page.view_state == "STATE456"
    assert page.row_count == 587
    assert len(page.rows) == 1
    row = page.rows[0]
    assert row.row_key == "1376"
    assert row.name == "Sampler, Robin Middle"
    assert row.reporting_agency == "FDLE - Tallahassee"
    assert row.incident_date == "11-02-2012"
    assert row.photo_url is not None and row.photo_url.startswith("https://web.fdle.state.fl.us/unsolvedcases/")


def test_parse_paginated_results_table_update() -> None:
    page = parse_results(PAGINATION_XML)

    assert page.row_count == 587
    assert page.rows[0].row_key == "1376"


def test_parse_paginated_results_row_fragment_update() -> None:
    page = parse_results(PAGINATION_ROWS_XML)

    assert page.view_state == "STATE789"
    assert page.rows[0].row_key == "1427"
    assert page.rows[0].name == "UNK-BF, Trout Lake (Alachua CSO)"


def test_build_row_select_payload() -> None:
    payload = build_row_select_payload(view_state="STATE456", row_key="1376")

    assert payload["javax.faces.source"] == "searchForm:resultsTable"
    assert payload["javax.faces.behavior.event"] == "rowSelect"
    assert payload["searchForm:resultsTable_selection"] == "1376"
    assert payload["searchForm:resultsTable_instantSelectedRowKey"] == "1376"


def test_parse_row_select_redirect() -> None:
    assert (
        parse_partial_redirect(
            '<partial-response><redirect url="/unsolvedcases/public/caseDetails.jsf"></redirect></partial-response>'
        )
        == "https://web.fdle.state.fl.us/unsolvedcases/public/caseDetails.jsf"
    )


def test_parse_case_detail_from_fdle_label_layout() -> None:
    detail = parse_case_detail(
        DETAIL_HTML,
        row_key="1376",
        source_url="https://web.fdle.state.fl.us/unsolvedcases/public/caseDetails.jsf",
    )

    assert detail.source_case_id == "1376"
    assert detail.case_title == 'Robin "Pig" Sampler Death Investigation (11/2012)'
    assert detail.victim_name == "Sampler, Robin Middle"
    assert detail.case_type == "Homicide"
    assert detail.incident_date == "11-02-2012"
    assert detail.narrative == "On Friday, November 2, 2012 FDLE opened the investigation."
    assert detail.dob is None
    assert detail.gender == "MALE"
    assert detail.race == "BLACK or AFRICAN AMERICAN"
    assert detail.incident_address == "101 Example Lane Quincy FL"
    assert detail.incident_city is None
    assert detail.agency_address == "202 Sample Avenue"
    assert detail.photos[0].source_url.startswith("https://web.fdle.state.fl.us/unsolvedcases/")
    assert detail.photos[0].source_url.endswith("/imageLoader?f=422")
    assert detail.photos[1].source_url.endswith("/imageLoader?f=1616")


def test_parse_case_detail_tolerates_empty_labels_before_about() -> None:
    detail = parse_case_detail(
        DETAIL_HTML_WITH_EMPTY_LABEL,
        row_key="1376",
        source_url="https://web.fdle.state.fl.us/unsolvedcases/public/caseDetails.jsf",
    )

    assert detail.narrative == "On Friday, November 2, 2012 FDLE opened the investigation."


def test_registry_and_source_catalog_include_fdle() -> None:
    registry = build_adapter_registry()
    assert registry.resolve_class("cold_case_fl_fdle").__name__ == "ColdCaseFLFDLEAdapter"

    catalog = SourceCatalog.from_yaml("src/casesignal/etl/sources")
    source = catalog.get("cold_case_fl_fdle_2026_05_22")
    assert source.adapter_name == "cold_case_fl_fdle"
    assert source.source_state == "FL"
    assert source.input_type == "url"


def test_register_hash_ignores_session_specific_photo_urls() -> None:
    base = {
        "source_case_id": "1376",
        "case_title": "Case",
        "photos": [{"source_url": "https://example.test/a?session=one", "filename_hint": "422.jpg"}],
    }
    changed_url = {
        **base,
        "photos": [{"source_url": "https://example.test/a?session=two", "filename_hint": "422.jpg"}],
    }

    assert canonical_entries_hash([base]) == canonical_entries_hash([changed_url])


def test_transform_normalizers_handle_fdle_shapes() -> None:
    assert _split_fdle_name("Sampler, Robin Middle") == ("Robin Middle", "Sampler")
    assert _split_fdle_name("Jane Doe") == ("Jane", "Doe")
    assert _normalize_fl_date("11-02-2012") == "2012-11-02"
    assert _normalize_fl_date("11/02/2012") == "2012-11-02"
    assert _normalize_case_type("Missing Person") == "missing_person"
    assert _normalize_case_type("Homicide") == "homicide"
