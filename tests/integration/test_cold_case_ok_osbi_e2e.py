"""End-to-end ingest test for the OK OSBI adapter.

Runs all five stages against a synthetic 2-page listing (mirroring the real
site's alphabetical range-page layout: an index that links range pages, each
range page holding inline AEM `cmp-teaser` case blocks -- there are no
per-case detail URLs for OK) plus a stub PoliteHTTPClient that serves them +
a tiny JPEG for the one photo URL. Verifies the canonical state for the
4-case slice:
  - 4 cases: 2 homicide + 1 missing_person + 1 suspicious_death
  - 1 case (Example) resolves source_county_fips via the narrative "<County>
    County" regex (Pottawatomie -> 40125); the other 3 have no county mention
  - 4 victim rows, 4 contact rows
  - 8 extraction jobs (Tier-1 + Tier-2 per case)
  - 4 geocoding jobs
  - 1 case_photo row (Example) with storage_path set

_MIN_EXPECTED_CASES / _MIN_EXPECTED_RANGE_PAGES are monkeypatched down to 3
and 2 so the small synthetic corpus doesn't trip the "site may have changed"
guards.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from sqlalchemy import text

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)

_TINY_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

_INDEX_URL = (
    "https://oklahoma.gov/osbi/services/investigative-services-division"
    "/cold-case-files/cold-cases.html"
)
_RANGE_A_B_URL = (
    "https://oklahoma.gov/osbi/services/investigative-services-division"
    "/cold-case-files/cold-case-files-a-b.html"
)
_RANGE_S_U_URL = (
    "https://oklahoma.gov/osbi/services/investigative-services-division"
    "/cold-case-files/cold-case-files-s-u.html"
)
_PHOTO_URL = (
    "https://oklahoma.gov/content/dam/ok/en/osbi/images/cold-case-images/ADAMS_JAMES.jpg"
)

# Synthetic index: links the two range pages the real site would list (only
# a slice of the real 10, but that's fine -- _MIN_EXPECTED_RANGE_PAGES is
# monkeypatched down to 2 below). Absolute hrefs, since the range-href regex
# requires a leading "/" immediately before "cold-case-files-".
_INDEX_HTML = f"""
<html><body>
<main>
  <a href="{_RANGE_A_B_URL}">A - B</a>
  <a href="{_RANGE_S_U_URL}">S - U</a>
</main>
</body></html>
"""


def _teaser(
    *,
    name: str,
    case_type_label: str,
    date_text: str,
    narrative: str,
    contact: str,
    photo_url: str | None = None,
) -> str:
    """One AEM cmp-teaser case block, matching the shape parse_range_page
    expects (synthetic markup matching its selectors):
    a title, a first-paragraph <b>Type<br/>Date</b> line, narrative
    paragraph(s), and a trailing 'If you have any information ...' contact
    paragraph. Photo is optional and lives in a sibling .cmp-teaser__image."""
    photo_html = (
        f'<div class="cmp-teaser__image"><img src="{photo_url}" alt="{name}"/></div>'
        if photo_url
        else ""
    )
    return f"""
    <div class="cmp-teaser">
      {photo_html}
      <div class="cmp-teaser__content">
        <h2 class="cmp-teaser__title">{name}</h2>
        <div class="cmp-teaser__description">
          <div class="cmp-text">
            <p><b>{case_type_label}<br/>{date_text}</b></p>
            <p>{narrative}</p>
            <p>{contact}</p>
          </div>
        </div>
      </div>
    </div>
    """


_ADAMS_CONTACT = (
    "For this invented example, please contact the OSBI via "
    "email cases@example.test"
)

_RANGE_A_B_HTML = f"""
<html><body><div class="teaser-list">
{_teaser(
    name="James Middle Example",
    case_type_label="Homicide",
    date_text="November 15, 1984",
    narrative=(
        "On November 15, 1984, the body of James Middle Example was found "
        "in Pottawatomie County. James had been shot in the head."
    ),
    contact=_ADAMS_CONTACT,
    photo_url=_PHOTO_URL,
)}
{_teaser(
    name="Casey E. Sampler",
    case_type_label="Missing Person",
    date_text="October 23, 2004",
    narrative="Casey E. Sampler was last seen in Geronimo, Oklahoma.",
    contact="For this invented example, please contact the OSBI.",
)}
</div></body></html>
"""

_RANGE_S_U_HTML = f"""
<html><body><div class="teaser-list">
{_teaser(
    name="John Suspicious",
    case_type_label="Suspicious Death",
    date_text="January 1, 2010",
    narrative="John Suspicious was found deceased under unusual circumstances.",
    contact="For this invented example, please contact the OSBI.",
)}
{_teaser(
    name="Robert Test Smith",
    case_type_label="Homicide",
    date_text="March 3, 1999",
    narrative="Robert Test Smith's body was found near a rural highway.",
    contact="For this invented example, please contact the OSBI.",
)}
</div></body></html>
"""


@dataclass
class _StubResponse:
    content: bytes = b""
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class _StubPoliteHttp:
    """Serves the synthetic index + the 2 synthetic range pages by URL; a
    tiny JPEG for the one photo URL (Example)."""

    def __init__(self, html_by_url: dict[str, str]) -> None:
        self._html_by_url = html_by_url

    def get(self, url: str) -> _StubResponse:
        if url in self._html_by_url:
            return _StubResponse(text=self._html_by_url[url])
        raise RuntimeError(f"_StubPoliteHttp.get: unexpected URL {url!r}")

    def head(self, url: str) -> _StubResponse:
        return _StubResponse(headers={"Content-Type": "image/jpeg"})

    def fetch_to_file(self, url: str, dest_path: Path) -> Path:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(_TINY_JPEG)
        return dest_path

    def close(self) -> None:
        pass


def test_ok_osbi_e2e_full_pipeline(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    import casesignal.etl.adapters.cold_case_ok_osbi.adapter as ok_adapter_mod
    import casesignal.etl.adapters.cold_case_ok_osbi.raw_load as ok_raw_load_mod
    from casesignal.etl.adapters.cold_case_ok_osbi.adapter import ColdCaseOKOSBIAdapter
    from casesignal.etl.runners.run_pipeline import build_pipeline_context
    from casesignal.etl.services.db import create_db_engine, create_session_factory
    from casesignal.etl.services.source_definition import SourceDefinition

    monkeypatch.setattr(ok_raw_load_mod, "_PHOTO_DIR_ROOT", tmp_path / "photos")
    # The synthetic corpus only has 2 range pages / 4 cases; the real
    # _MIN_EXPECTED_RANGE_PAGES=10 / _MIN_EXPECTED_CASES=250 guards are a
    # "site changed" tripwire that doesn't apply to this fixture slice.
    monkeypatch.setattr(ok_adapter_mod, "_MIN_EXPECTED_RANGE_PAGES", 2)
    monkeypatch.setattr(ok_adapter_mod, "_MIN_EXPECTED_CASES", 3)

    html_by_url = {
        _INDEX_URL: _INDEX_HTML,
        _RANGE_A_B_URL: _RANGE_A_B_HTML,
        _RANGE_S_U_URL: _RANGE_S_U_HTML,
    }
    stub = _StubPoliteHttp(html_by_url)
    monkeypatch.setattr(ok_adapter_mod, "PoliteHTTPClient", lambda **kwargs: stub)

    engine = create_db_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    source_def = SourceDefinition(
        source_key="cold_case_ok_osbi_e2e",
        source_family="cold_case",
        adapter_name="cold_case_ok_osbi",
        source_code="OSBI_OK_E2E_TEST",
        source_name="OK OSBI Cold Cases (e2e test fixture)",
        source_year=2026,
        source_state="OK",
        input_path=Path(_INDEX_URL),
        input_type="url",
        description="Test fixture run",
        required_files=frozenset(),
        optional_files=frozenset(),
        metadata={"source_url": _INDEX_URL, "rate_limit_seconds": 0.0},
    )

    context = build_pipeline_context(source_def, logging.getLogger("test_ok_osbi_e2e"))
    context.set_metadata("session_factory", session_factory)

    adapter = ColdCaseOKOSBIAdapter(source_def)
    adapter.prepare_input(context)
    adapter.register_source(context)
    adapter.load_raw(context)
    adapter.transform(context)

    dv = context.dataset_version_id
    assert dv is not None, "register_source must set dataset_version_id"

    try:
        with session_factory() as session:
            n_cases = session.execute(
                text("SELECT COUNT(*) FROM cold_case.cases WHERE dataset_version_id = :dv"),
                {"dv": dv},
            ).scalar_one()
            assert n_cases == 4, f"expected 4 cases, got {n_cases}"

            by_type: dict[str, int] = {
                str(row[0]): int(row[1])
                for row in session.execute(
                    text(
                        "SELECT case_type, COUNT(*) FROM cold_case.cases "
                        "WHERE dataset_version_id = :dv GROUP BY case_type"
                    ),
                    {"dv": dv},
                )
            }
            assert by_type == {
                "homicide": 2,
                "missing_person": 1,
                "suspicious_death": 1,
            }, by_type

            n_victims = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.victim v "
                    "JOIN cold_case.cases c ON c.case_id = v.case_id "
                    "WHERE c.dataset_version_id = :dv"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_victims == 4, f"expected 4 victims, got {n_victims}"

            n_contacts = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.contact ct "
                    "JOIN cold_case.cases c ON c.case_id = ct.case_id "
                    "WHERE c.dataset_version_id = :dv"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_contacts == 4, f"expected 4 contacts, got {n_contacts}"

            by_tier: dict[int, int] = {
                int(row[0]): int(row[1])
                for row in session.execute(
                    text(
                        "SELECT prompt_tier, COUNT(*) FROM cold_case.extraction_job j "
                        "JOIN cold_case.cases c ON c.case_id = j.case_id "
                        "WHERE c.dataset_version_id = :dv GROUP BY prompt_tier"
                    ),
                    {"dv": dv},
                )
            }
            assert by_tier == {1: 4, 2: 4}, f"expected 4/4 by tier, got {by_tier}"

            n_geo = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.geocoding_job j "
                    "JOIN cold_case.cases c ON c.case_id = j.case_id "
                    "WHERE c.dataset_version_id = :dv"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_geo == 4, f"expected 4 geocoding jobs, got {n_geo}"

            example = session.execute(
                text(
                    "SELECT source_county_fips FROM cold_case.cases "
                    "WHERE dataset_version_id = :dv "
                    "AND source_case_id = 'james-middle-example-1984-11-15'"
                ),
                {"dv": dv},
            ).scalar_one()
            assert example == "40125", f"expected Pottawatomie County FIPS, got {example!r}"

            n_fips = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.cases "
                    "WHERE dataset_version_id = :dv AND source_county_fips IS NOT NULL"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_fips == 1, f"expected exactly 1 county-floor case, got {n_fips}"

            n_photos = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.case_photo cp "
                    "JOIN cold_case.cases c ON c.case_id = cp.case_id "
                    "WHERE c.dataset_version_id = :dv"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_photos == 1, f"expected 1 photo (Example), got {n_photos}"

            n_no_path = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.case_photo cp "
                    "JOIN cold_case.cases c ON c.case_id = cp.case_id "
                    "WHERE c.dataset_version_id = :dv AND cp.storage_path IS NULL"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_no_path == 0, f"{n_no_path} photos missing storage_path"
    finally:
        with session_factory() as session:
            for tbl in (
                "geocoding_job",
                "extraction_job",
                "case_extractions",
                "case_photo",
                "victim",
                "contact",
            ):
                session.execute(
                    text(
                        f"DELETE FROM cold_case.{tbl} WHERE case_id IN "
                        "(SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
                    ),
                    {"dv": dv},
                )
            session.execute(
                text("DELETE FROM cold_case.cases WHERE dataset_version_id = :dv"),
                {"dv": dv},
            )
            session.execute(
                text(f"DROP TABLE IF EXISTS raw_cold_case.cold_case_ok_osbi_dv{dv}")
            )
            session.execute(
                text("DELETE FROM etl.ingestion_run WHERE dataset_version_id = :dv"),
                {"dv": dv},
            )
            session.execute(
                text("DELETE FROM etl.dataset_version WHERE dataset_version_id = :dv"),
                {"dv": dv},
            )
            session.execute(
                text("DELETE FROM etl.source_system WHERE source_code = :c"),
                {"c": "OSBI_OK_E2E_TEST"},
            )
            session.commit()
