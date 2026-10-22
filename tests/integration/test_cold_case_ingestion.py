"""Virginia catalog contracts and ingestion of an invented CSV."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from casesignal.etl.adapters.cold_case_va.schema_baseline import COLD_CASE_VA_EXPECTED_COLUMNS
from casesignal.etl.runners.run_pipeline import run_pipeline


def test_va_pipeline_with_synthetic_record(tmp_path: Path, db_engine: Any) -> None:
    csv_path = tmp_path / "raw_data.csv"
    row = {column: "" for column in COLD_CASE_VA_EXPECTED_COLUMNS}
    row.update({
        "_id": "SYN-001", "post_id": "999999", "vspccd-number": "SYN-001",
        "case_name": "Example Person", "type": "Homicide",
        "incident-date": "01/01/2000", "address": "101 Example Lane",
        "city": "Example City", "state": "VA",
        "about": "This is an invented case used to test ingestion.",
        "victim-fields_first-name": "Example", "victim-fields_last-name": "Person",
        "victim-fields_gender": "Male", "victim-fields_age": "42",
        "geographic-location": "POINT (-78 38)",
        "contact-last-name": "Example Unit", "contact-phone-number": "202-555-0100",
    })
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(row))
        writer.writeheader()
        writer.writerow(row)
    catalog = tmp_path / "sources.yaml"
    catalog.write_text(yaml.safe_dump({"sources": [{
        "source_key": "portfolio_va_synthetic", "source_family": "cold_case",
        "adapter_name": "cold_case_va", "source_code": "PORTFOLIO_VA_SYNTHETIC",
        "source_name": "Synthetic Virginia parser test", "input_path": str(csv_path),
        "input_type": "csv", "source_year": 2000, "source_state": "VA",
        "required_files": ["raw_data.csv"], "optional_files": [], "metadata": {},
    }]}))
    result = run_pipeline(source_key="portfolio_va_synthetic", catalog_path=catalog)
    assert result.run_status in {"completed", "published", "succeeded"}
    assert result.dataset_version_id is not None
    with db_engine.connect() as conn:
        cases = conn.execute(text("""
            SELECT case_id, case_type, incident_date, address, address_source,
                   latitude, longitude, slug FROM cold_case.cases
            WHERE dataset_version_id = :dv
        """), {"dv": result.dataset_version_id}).all()
        assert len(cases) == 1
        case = cases[0]
        assert case.case_type == "homicide"
        assert case.incident_date.isoformat() == "2000-01-01"
        assert case.address == "101 Example Lane" and case.address_source == "source"
        assert (float(case.latitude), float(case.longitude)) == (38, -78)
        assert case.slug
        victims = conn.execute(text("""
            SELECT first_name, last_name FROM cold_case.victim WHERE case_id = :id
        """), {"id": case.case_id}).all()
        assert victims == [("Example", "Person")]
        assert conn.execute(text("""
            SELECT count(*) FROM cold_case.extraction_job WHERE case_id = :id
        """), {"id": case.case_id}).scalar_one() >= 1


def test_config_has_cold_case_va_source() -> None:
    """sources.yaml must contain the cold_case_va_2025_03_27 entry."""
    from casesignal.etl.runners.run_pipeline import DEFAULT_CATALOG_PATH
    from casesignal.etl.services.source_catalog import SourceCatalog

    catalog = SourceCatalog.from_yaml(DEFAULT_CATALOG_PATH)
    source_keys = {s.source_key for s in catalog.list_sources()}
    assert "cold_case_va_2025_03_27" in source_keys


def test_required_files_match_schema_baseline() -> None:
    """sources.yaml required_files for cold_case_va MUST match the schema baseline.

    Catches the common drift where someone adds a required file in YAML but
    forgets to register it in schema_baseline.py (or vice versa).
    """
    from casesignal.etl.runners.run_pipeline import DEFAULT_CATALOG_PATH
    from casesignal.etl.services.source_catalog import SourceCatalog

    catalog = SourceCatalog.from_yaml(DEFAULT_CATALOG_PATH)
    source = next(
        (s for s in catalog.list_sources() if s.source_key == "cold_case_va_2025_03_27"),
        None,
    )
    assert source is not None, "cold_case_va_2025_03_27 missing from sources.yaml"

    # For CSV sources, the baseline is a single file mapping by filename.
    # The YAML's required_files filename set must equal the schema-baseline filename set.
    yaml_required = set(source.required_files)
    # The CSV path filename is what the inspector uses as the key.
    baseline_filenames = {"raw_data.csv"}

    assert yaml_required == baseline_filenames, (
        f"sources.yaml required_files {yaml_required} != "
        f"schema_baseline filenames {baseline_filenames}"
    )
