"""Wyoming DCI end-to-end: fixture CSV + photos -> all 5 adapter stages -> canonical rows.

Mirrors the OH AG e2e harness shape:
  - build_pipeline_context + session_factory injection
  - synthetic CSV + photo fixtures written to tmp_path
  - all 5 adapter stages run in order (publish omitted — see below)
  - assertions on cold_case.cases / victim / contact / case_extractions /
    case_photo / geocoding_job / extraction_job (this last MUST be 0 — the
    WY signature)
  - cleanup via dataset_version_id FK cascade

Unlike OH AG / UT, WY's raw_load is filesystem-only (no polite_http to
mock). We do, however, monkeypatch:
  - raw_load._MIN_ROWS (25 → 3) so the 3-row fixture clears the floor
  - transform.PHOTO_SRC_DIR / PHOTO_DST_ROOT to the test's tmp dirs
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from sqlalchemy import text

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping integration test", allow_module_level=True)


# 1x1 minimal PNG (25 bytes). transform copies bytes verbatim and stamps
# content_type='image/jpeg' without sniffing, so a PNG-bytes-as-.jpg is fine.
_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc"
    b"\xff\xff?\x00\x05\xfe\x02\xfe\xa1g\xc3\x9c\x00\x00\x00\x00IEND\xaeB`\x82"
)


# 3-row fixture CSV.
#   Row 1: complete (named victim, Handgun, Home, full address, photo)
#   Row 2: unidentified victim, no address, no photo (geocode falls back to 'Wyoming')
#   Row 3: named victim, Casper city only (no street), no photo
# Synopses are all ≥ 50 chars to clear raw_load's _MIN_SYNOPSIS_LEN guard.
_FIXTURE_CSV = (
    "source_case_id,reported_date,crime_types,weapon,victim_name,victim_age,"
    "victim_sex,victim_race,scene_type,scene_address,scene_business_name,"
    "scene_city,scene_county,synopsis,photo_filename\n"
    "wy-test-001-doe,2010-05-01,Homicide,Handgun,Jane Doe,34,Female,White,Home,"
    "123 Test St,,Cheyenne,Laramie,"
    "Jane Doe was found deceased in her home on May 1 2010. Local PD opened a homicide investigation.,"
    "wy-test-001-doe.jpg\n"
    'wy-test-002-unidentified,2005-08-15,"Homicide, Unidentified Remains",Other,,'
    ",,,Desert,,,,Sweetwater,"
    "Unidentified human remains were discovered in the desert near Wamsutter on August 15 2005.,\n"
    "wy-test-003-roe,2018-11-20,Homicide,Knife,John Roe,42,Male,Black,Business,,,"
    "Casper,Natrona,"
    "John Roe was killed during a robbery at a business in Casper on November 20 2018 in the evening.,\n"
)


def test_wy_dci_e2e_full_pipeline(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Run all 5 WY DCI adapter stages against a 3-row CSV fixture.

    Verifies:
      - prepare_input / register_source / load_raw / transform run cleanly
      - 3 canonical cold_case.cases rows land
      - ZERO extraction_job rows are queued (WY's signal: no LLM)
      - 3 synthetic case_extractions rows at (prompt_tier=1, model_id='source')
      - weapon + location_type normalization is correct
      - exactly 1 case_photo row (only row 1 had a photo_filename)
      - 3 geocoding_job rows (all three enqueue, with state-only fallback for row 2)
      - incident_date_source = 'source' on all 3 rows
    """
    from casesignal.etl.adapters.cold_case_wy_dci.adapter import ColdCaseWyDciAdapter
    from casesignal.etl.runners.run_pipeline import build_pipeline_context
    from casesignal.etl.services.db import create_db_engine, create_session_factory
    from casesignal.etl.services.source_definition import SourceDefinition

    # --- fixture filesystem layout ---------------------------------------
    base = tmp_path / "wy_fixture"
    photos_dir = base / "photos"
    photos_dir.mkdir(parents=True)
    (photos_dir / "wy-test-001-doe.jpg").write_bytes(_ONE_PIXEL_PNG)
    csv_path = base / "wyoming_dci_cold_cases.csv"
    csv_path.write_text(_FIXTURE_CSV, encoding="utf-8")

    # transform reads module-level PHOTO_SRC_DIR / PHOTO_DST_ROOT — point
    # them at the test's tmp dirs so we never touch data/ in the workspace.
    import casesignal.etl.adapters.cold_case_wy_dci.transform as wy_transform

    monkeypatch.setattr(wy_transform, "PHOTO_SRC_DIR", photos_dir)
    monkeypatch.setattr(wy_transform, "PHOTO_DST_ROOT", tmp_path / "photos_dst")

    # raw_load enforces _MIN_ROWS=25 against real-extract row counts; relax
    # for the fixture. Same for _MIN_SYNOPSIS_LEN guarantees on row content
    # — keep that at its real value (50) and write synopses that clear it.
    import casesignal.etl.adapters.cold_case_wy_dci.raw_load as wy_raw_load

    monkeypatch.setattr(wy_raw_load, "_MIN_ROWS", 3)

    # --- DB plumbing -----------------------------------------------------
    engine = create_db_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    source_def = SourceDefinition(
        source_key="cold_case_wy_dci_e2e_test",
        source_family="cold_case",
        adapter_name="cold_case_wy_dci",
        source_code="WY_DCI_E2E_TEST",
        source_name="Wyoming DCI Cold Cases (e2e test fixture)",
        source_year=2026,
        source_state="WY",
        input_path=csv_path,
        input_type="csv",
        description="Test fixture run",
        required_files=frozenset(),
        optional_files=frozenset(),
        metadata={"baseline_count": 3, "photos_dir": str(photos_dir)},
    )

    logger = logging.getLogger("test_wy_dci_e2e")
    context = build_pipeline_context(source_def, logger)
    context.set_metadata("session_factory", session_factory)

    adapter = ColdCaseWyDciAdapter(source_def)

    adapter.prepare_input(context)
    adapter.register_source(context)
    adapter.load_raw(context)
    adapter.transform(context)
    # publish() is intentionally omitted — it advances dataset_version
    # ingestion_status and the 5-stage contract permits per-test omission
    # (matches the OH AG e2e harness).

    dv = context.dataset_version_id
    assert dv is not None, "register_source must set dataset_version_id"

    try:
        with session_factory() as session:
            # Exactly 3 cases land.
            n_cases = session.execute(
                text("SELECT COUNT(*) FROM cold_case.cases " "WHERE dataset_version_id = :dv"),
                {"dv": dv},
            ).scalar_one()
            assert n_cases == 3, f"expected 3 cases, got {n_cases}"

            # WY signal #1: zero extraction_job rows queued.
            n_jobs = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.extraction_job ej "
                    "JOIN cold_case.cases c ON c.case_id = ej.case_id "
                    "WHERE c.dataset_version_id = :dv"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_jobs == 0, "WY must NOT enqueue any LLM extraction jobs"

            # WY signal #2: 3 synthetic source-MO rows at prompt_tier=1,
            # model_id='source'.
            n_synth = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.case_extractions ce "
                    "JOIN cold_case.cases c ON c.case_id = ce.case_id "
                    "WHERE c.dataset_version_id = :dv "
                    "  AND ce.prompt_tier = 1 "
                    "  AND ce.model_id = 'source'"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_synth == 3, f"expected 3 synthetic extractions, got {n_synth}"

            # Spot-check weapon + location_type normalization on row 1.
            row1 = session.execute(
                text(
                    "SELECT ce.weapon, ce.location_type "
                    "  FROM cold_case.case_extractions ce "
                    "  JOIN cold_case.cases c ON c.case_id = ce.case_id "
                    " WHERE c.source_case_id = 'wy-test-001-doe' "
                    "   AND ce.model_id = 'source'"
                ),
            ).first()
            assert row1 is not None
            assert row1.weapon == "firearm", f"Handgun → firearm, got {row1.weapon!r}"
            assert (
                row1.location_type == "residence"
            ), f"Home → residence, got {row1.location_type!r}"

            # Spot-check row 3: Knife → knife, Business → commercial.
            row3 = session.execute(
                text(
                    "SELECT ce.weapon, ce.location_type "
                    "  FROM cold_case.case_extractions ce "
                    "  JOIN cold_case.cases c ON c.case_id = ce.case_id "
                    " WHERE c.source_case_id = 'wy-test-003-roe' "
                    "   AND ce.model_id = 'source'"
                ),
            ).first()
            assert row3 is not None
            assert row3.weapon == "knife", f"Knife → knife, got {row3.weapon!r}"
            assert (
                row3.location_type == "commercial"
            ), f"Business → commercial, got {row3.location_type!r}"

            # Photo: only row 1 had a photo_filename.
            n_photos = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.case_photo p "
                    "JOIN cold_case.cases c ON c.case_id = p.case_id "
                    "WHERE c.dataset_version_id = :dv"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_photos == 1, f"expected 1 photo row, got {n_photos}"

            # Geocoding queued for all 3 cases — row 2 falls back to bare
            # 'Wyoming' (no scene_address, no scene_city).
            n_geo = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.geocoding_job gj "
                    "JOIN cold_case.cases c ON c.case_id = gj.case_id "
                    "WHERE c.dataset_version_id = :dv"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_geo == 3, f"expected 3 geocoding jobs, got {n_geo}"

            # Provenance: all 3 cases have incident_date_source='source'
            # (every fixture row has a non-null reported_date).
            n_prov = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.cases "
                    "WHERE dataset_version_id = :dv "
                    "  AND incident_date_source = 'source'"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_prov == 3, f"expected 3 source-dated cases, got {n_prov}"

            # Victim spot-check: row 2's blank victim_name → ('Unknown', '').
            v2 = session.execute(
                text(
                    "SELECT v.first_name, v.last_name "
                    "  FROM cold_case.victim v "
                    "  JOIN cold_case.cases c ON c.case_id = v.case_id "
                    " WHERE c.source_case_id = 'wy-test-002-unidentified'"
                ),
            ).first()
            assert v2 is not None
            assert v2.first_name == "Unknown"

            # Contact: agency-line, attributed uniformly to Wyoming DCI.
            n_contact = session.execute(
                text(
                    "SELECT COUNT(*) FROM cold_case.contact ct "
                    "JOIN cold_case.cases c ON c.case_id = ct.case_id "
                    "WHERE c.dataset_version_id = :dv "
                    "  AND ct.last_name = 'Wyoming Division of Criminal Investigation'"
                ),
                {"dv": dv},
            ).scalar_one()
            assert n_contact == 3, f"expected 3 DCI contact rows, got {n_contact}"
    finally:
        # Cleanup: delete in FK-safe order, then raw table, then registry.
        with session_factory() as session:
            session.execute(
                text(
                    "DELETE FROM cold_case.geocoding_job WHERE case_id IN ("
                    "SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
                ),
                {"dv": dv},
            )
            session.execute(
                text(
                    "DELETE FROM cold_case.case_photo WHERE case_id IN ("
                    "SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
                ),
                {"dv": dv},
            )
            session.execute(
                text(
                    "DELETE FROM cold_case.case_extractions WHERE case_id IN ("
                    "SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
                ),
                {"dv": dv},
            )
            session.execute(
                text(
                    "DELETE FROM cold_case.victim WHERE case_id IN ("
                    "SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
                ),
                {"dv": dv},
            )
            session.execute(
                text(
                    "DELETE FROM cold_case.contact WHERE case_id IN ("
                    "SELECT case_id FROM cold_case.cases WHERE dataset_version_id = :dv)"
                ),
                {"dv": dv},
            )
            session.execute(
                text("DELETE FROM cold_case.cases WHERE dataset_version_id = :dv"),
                {"dv": dv},
            )
            session.execute(text(f"DROP TABLE IF EXISTS raw_cold_case.cold_case_wy_dci_dv{dv}"))
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
                {"c": "WY_DCI_E2E_TEST"},
            )
            session.commit()
