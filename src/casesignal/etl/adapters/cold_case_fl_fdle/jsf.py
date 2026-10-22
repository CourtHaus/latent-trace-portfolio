"""JSF/PrimeFaces helpers for FDLE's unsolved-cases portal."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE_URL = "https://web.fdle.state.fl.us"
SEARCH_URL = f"{BASE_URL}/unsolvedcases/public/search.jsf"
DETAIL_URL = f"{BASE_URL}/unsolvedcases/public/caseDetails.jsf"


@dataclass(frozen=True, slots=True)
class FDLESearchRow:
    row_key: str
    name: str | None
    dob: str | None
    race: str | None
    gender: str | None
    reporting_agency: str | None
    incident_date: str | None
    photo_url: str | None


@dataclass(frozen=True, slots=True)
class FDLEResultPage:
    rows: list[FDLESearchRow]
    view_state: str
    row_count: int | None


@dataclass(frozen=True, slots=True)
class FDLEPhoto:
    source_url: str
    filename_hint: str | None = None
    alt: str | None = None


@dataclass(frozen=True, slots=True)
class FDLECaseDetail:
    source_case_id: str
    source_detail_url: str
    case_title: str | None = None
    victim_name: str | None = None
    case_type: str | None = None
    incident_date: str | None = None
    incident_address: str | None = None
    incident_city: str | None = None
    reporting_agency: str | None = None
    agency_phone: str | None = None
    agency_address: str | None = None
    gender: str | None = None
    race: str | None = None
    height: str | None = None
    weight_lbs: int | None = None
    dob: str | None = None
    narrative: str | None = None
    photos: list[FDLEPhoto] = field(default_factory=list)


def parse_captcha_answer(html_text: str) -> str:
    """Return the CAPTCHA answer exposed in the search input title.

    FDLE renders the CAPTCHA answer directly into the search input's
    ``title`` attribute (e.g. ``title="Enter Captcha Text 1234"``). The
    underlying data is public; the CAPTCHA is a decorative bot filter, not
    an access-control gate (project policy: "bot filter != access denial").
    See ``src/casesignal/etl/sources/cold_case_fl.yaml`` for the policy note.
    If this raises post-deploy, FDLE has likely moved to a real CAPTCHA and
    the ingestion needs to be paused.
    """
    match = re.search(r"Enter Captcha Text\s+(\d+)", html_text)
    if match is None:
        raise ValueError("FDLE CAPTCHA answer was not present in the page title attribute.")
    return match.group(1)


def parse_view_state(html_text: str) -> str:
    """Return the first JSF ViewState value in a document or partial response."""
    match = re.search(
        r'<update id="j_id1:javax\.faces\.ViewState:\d+"><!\[CDATA\[(.*?)\]\]>',
        html_text,
        flags=re.S,
    )
    if match:
        return match.group(1).strip()

    soup = BeautifulSoup(html_text, "html.parser")
    for inp in soup.find_all("input", attrs={"name": "javax.faces.ViewState"}):
        value = inp.get("value")
        if value:
            return str(value)

    raise ValueError("JSF ViewState was not found.")


def build_search_payload(
    *,
    view_state: str,
    captcha_answer: str,
    case_type: str,
    first_row: int = 0,
    rows: int = 50,
) -> dict[str, Any]:
    """Build the PrimeFaces AJAX search payload for one case type."""
    payload: dict[str, Any] = _base_search_form_payload(view_state)
    payload.update(
        {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "searchForm:searchBtn",
            "javax.faces.partial.execute": "searchForm",
            "javax.faces.partial.render": "searchForm growl",
            "searchForm:searchBtn": "searchForm:searchBtn",
            "searchForm:caseType_input": case_type,
            "searchForm:captchaInput": captcha_answer,
            "searchForm:resultsTable_first": str(first_row),
            "searchForm:resultsTable_rows": str(rows),
        }
    )
    return payload


def build_pagination_payload(
    *,
    view_state: str,
    first_row: int,
    rows: int = 50,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": "searchForm:resultsTable",
        "javax.faces.partial.execute": "searchForm:resultsTable",
        "javax.faces.partial.render": "searchForm:resultsTable",
        "searchForm:resultsTable": "searchForm:resultsTable",
        "searchForm:resultsTable_pagination": "true",
        "searchForm:resultsTable_first": str(first_row),
        "searchForm:resultsTable_rows": str(rows),
        "searchForm:resultsTable_encodeFeature": "true",
        "searchForm": "searchForm",
        "javax.faces.ViewState": view_state,
    }
    return payload


def build_row_select_payload(*, view_state: str, row_key: str) -> dict[str, Any]:
    return {
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": "searchForm:resultsTable",
        "javax.faces.partial.execute": "searchForm:resultsTable",
        "javax.faces.partial.render": "searchForm",
        "javax.faces.behavior.event": "rowSelect",
        "javax.faces.partial.event": "rowSelect",
        "searchForm": "searchForm",
        "searchForm:resultsTable_selection": row_key,
        "searchForm:resultsTable_instantSelectedRowKey": row_key,
        "javax.faces.ViewState": view_state,
    }


def parse_results(response_text: str) -> FDLEResultPage:
    html_text = (
        _extract_update(response_text, "searchForm")
        or _extract_update(response_text, "searchForm:resultsTable")
        or response_text
    )
    soup = BeautifulSoup(html_text, "html.parser")
    rows: list[FDLESearchRow] = []
    table_rows = soup.select("#searchForm\\:resultsTable_data tr[data-rk]")
    if not table_rows:
        table_rows = soup.select("tr[data-rk]")
    for tr in table_rows:
        row_key = str(tr.get("data-rk") or "").strip()
        if not row_key:
            continue
        cells = tr.find_all("td", recursive=False)
        name = _text_one(tr, '[id$="nameTable"]')
        if not name and len(cells) > 1:
            name = _clean_text(cells[1].get_text(" ", strip=True))
        rows.append(
            FDLESearchRow(
                row_key=row_key,
                name=name,
                dob=_text_one(tr, '[id$="dobTable"]'),
                race=_text_one(tr, '[id$="raceTable"]'),
                gender=_text_one(tr, '[id$="genderTable"]'),
                reporting_agency=_cell_text(cells, 5),
                incident_date=_cell_text(cells, 6),
                photo_url=_abs_url(_first_img_src(tr)),
            )
        )
    return FDLEResultPage(
        rows=rows,
        view_state=parse_view_state(response_text),
        row_count=_parse_row_count(response_text),
    )


def parse_partial_redirect(response_text: str) -> str | None:
    match = re.search(r"<redirect\s+url=\"([^\"]+)\"", response_text)
    if match is None:
        return None
    return _abs_url(match.group(1))


def parse_case_detail(html_text: str, *, row_key: str, source_url: str) -> FDLECaseDetail:
    soup = BeautifulSoup(html_text, "html.parser")
    case_form = soup.select_one("#caseDetailsForm") or soup

    sections = _section_fields(case_form)
    case_fields = sections.get("case", {})
    subject_fields = sections.get("subject", {})
    agency_fields = sections.get("agency", {})

    case_fs18 = _section_fs18(case_form, "case")
    subject_fs18 = _section_fs18(case_form, "subject")

    incident_address = case_fields.get("Address")
    agency_address = agency_fields.get("Address")
    photos = _extract_photos(soup)

    return FDLECaseDetail(
        source_case_id=row_key,
        source_detail_url=source_url,
        case_title=case_fs18,
        victim_name=subject_fs18,
        case_type=case_fields.get("Case Type"),
        incident_date=case_fields.get("Incident Date"),
        incident_address=incident_address,
        incident_city=None,  # FDLE's case-section address isn't reliably splittable; geocoding uses the full string
        reporting_agency=agency_fields.get("Name"),
        agency_phone=agency_fields.get("Contact Phone"),
        agency_address=agency_address,
        gender=subject_fields.get("Gender"),
        race=subject_fields.get("Race"),
        height=None,
        weight_lbs=None,
        dob=None,
        narrative=case_fields.get("About this case"),
        photos=photos,
    )


def _base_search_form_payload(view_state: str) -> dict[str, Any]:
    return {
        "searchForm": "searchForm",
        "searchForm:firstName": "",
        "searchForm:middleName": "",
        "searchForm:lastName": "",
        "searchForm:alias": "",
        "searchForm:race_input": "",
        "searchForm:gender_input": "",
        "searchForm:identifyingMarks": "",
        "searchForm:j_idt38_collapsed": "false",
        "searchForm:agency_input": "",
        "searchForm:caseType_input": "",
        "searchForm:crimeDateStart_input": "",
        "searchForm:crimeDateEnd_input": "",
        "searchForm:caseInfo": "",
        "searchForm:weapons_input": "",
        "searchForm:vehicleExteriorColor": "",
        "searchForm:vehicleMake_input": "",
        "searchForm:j_idt66_collapsed": "false",
        "searchForm:captchaInput": "",
        "javax.faces.ViewState": view_state,
    }


def _extract_update(response_text: str, update_id: str) -> str | None:
    pattern = rf'<update id="{re.escape(update_id)}"><!\[CDATA\[(.*?)\]\]></update>'
    match = re.search(pattern, response_text, flags=re.S)
    if not match:
        return None
    return html.unescape(match.group(1))


def _parse_row_count(response_text: str) -> int | None:
    match = re.search(r"rowCount\s*:\s*(\d+)", response_text)
    return int(match.group(1)) if match else None


def _text_one(root: Any, selector: str) -> str | None:
    node = root.select_one(selector)
    return _clean_text(node.get_text(" ", strip=True)) if node else None


def _cell_text(cells: list[Any], index: int) -> str | None:
    if index >= len(cells):
        return None
    return _clean_text(cells[index].get_text(" ", strip=True))


def _first_img_src(root: Any) -> str | None:
    img = root.find("img")
    return str(img.get("src")) if img and img.get("src") else None


def _abs_url(url: str | None) -> str | None:
    if not url:
        return None
    absolute = urljoin(BASE_URL, html.unescape(url))
    if absolute.startswith("http://web.fdle.state.fl.us/"):
        absolute = "https://" + absolute[len("http://") :]
    return absolute


_SECTION_MARKERS: dict[str, str] = {
    "case information": "case",
    "subject information": "subject",
    "reporting agency information": "agency",
}

_SECTION_STOP_CLASSES = {"ui-outputlabel", "ui-reflow-label", "ui-paginator-rpp-label"}


def _section_fields(root: Any) -> dict[str, dict[str, str]]:
    """Walk labels in document order, tracking section boundaries via Fs24 markers.

    Returns a dict of {section_key: {field_label: field_value}} where section_key
    is one of "case", "subject", "agency". Only the first matching section for each
    key is populated (expected: exactly one of each per page).
    """
    result: dict[str, dict[str, str]] = {"case": {}, "subject": {}, "agency": {}}
    labels = root.find_all("label")
    current_section: str | None = None

    idx = 0
    while idx < len(labels):
        label = labels[idx]
        classes: set[str] = set(label.get("class") or [])

        # Stop at CAPTCHA / pagination noise
        if classes & _SECTION_STOP_CLASSES:
            break

        raw = _clean_text(label.get_text(" ", strip=True))

        # Section boundary detection: Fs24 label whose text names a section
        if "Fs24" in classes and raw:
            key = next(
                (v for k, v in _SECTION_MARKERS.items() if raw.lower().startswith(k)),
                None,
            )
            if key is not None:
                current_section = key
                idx += 1
                continue

        if current_section is None or not raw or not raw.endswith(":"):
            idx += 1
            continue

        field_key = raw.rstrip(":").strip()
        # Find next sibling label that is a non-empty non-key value
        value: str | None = None
        for nxt in labels[idx + 1 : idx + 5]:
            nxt_classes: set[str] = set(nxt.get("class") or [])
            if nxt_classes & _SECTION_STOP_CLASSES:
                break
            if "Fs24" in nxt_classes:
                break  # hit next section boundary before finding a value
            candidate = _clean_text(nxt.get_text(" ", strip=True))
            if candidate and not candidate.endswith(":"):
                value = candidate
                break
        if value:
            result[current_section].setdefault(field_key, value)

        idx += 1

    return result


def _section_fs18(root: Any, section: str) -> str | None:
    """Return the Fs18 label text belonging to ``section`` (case or subject).

    Walks labels in document order; once the section's Fs24 boundary is found,
    returns the next Fs18 label that appears before the next Fs24 boundary.
    """
    labels = root.find_all("label")
    in_target = False
    for label in labels:
        classes: set[str] = set(label.get("class") or [])
        if classes & _SECTION_STOP_CLASSES:
            break
        raw = _clean_text(label.get_text(" ", strip=True))
        if "Fs24" in classes and raw:
            matched_section = next(
                (v for k, v in _SECTION_MARKERS.items() if raw.lower().startswith(k)),
                None,
            )
            if matched_section == section:
                in_target = True
                continue
            elif in_target:
                # Next Fs24 — left the target section
                break
        if in_target and "Fs18" in classes and raw:
            return raw
    return None


def _extract_photos(soup: BeautifulSoup) -> list[FDLEPhoto]:
    urls: list[str] = []
    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content"):
        urls.append(str(og_image.get("content")))
    for img in soup.find_all("img"):
        src = str(img.get("src") or "")
        if "dynamiccontent.properties.jsf" in src or "imageLoader" in src:
            reusable = _reusable_photo_url(src)
            if reusable:
                urls.append(reusable)
    seen: set[str] = set()
    photos: list[FDLEPhoto] = []
    for raw_url in urls:
        url = _abs_url(raw_url)
        if not url or url in seen:
            continue
        seen.add(url)
        photos.append(FDLEPhoto(source_url=url, filename_hint=_photo_filename_hint(url)))
    return photos


def _photo_filename_hint(url: str) -> str | None:
    match = re.search(r"(?:SUB|SUP)_REL_OBJ_FILEID=(\d+)|[?&]f=(\d+)", url)
    if not match:
        return None
    ident = next(g for g in match.groups() if g)
    return f"{ident}.jpg"


def _reusable_photo_url(url: str) -> str | None:
    match = re.search(r"(?:SUB|SUP)_REL_OBJ_FILEID=(\d+)|[?&]f=(\d+)", html.unescape(url))
    if not match:
        return None
    ident = next(g for g in match.groups() if g)
    return f"{BASE_URL}/unsolvedcases/imageLoader?f={ident}"


def _clean_text(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned or None
