"""Source catalog test — ensures Phase 1.7 source keys are loadable."""

from casesignal.etl.services.source_catalog import SourceCatalog


def test_phase_1_7_sources_present() -> None:
    catalog = SourceCatalog.from_yaml("src/casesignal/etl/sources")
    keys = set(catalog.list_keys())
    assert "cold_case_md_charles_2026_05_09" in keys
    assert "cold_case_md_wicomico_2026_05_09" in keys


def test_charles_source_metadata() -> None:
    catalog = SourceCatalog.from_yaml("src/casesignal/etl/sources")
    src = catalog.get("cold_case_md_charles_2026_05_09")
    assert src.adapter_name == "cold_case_md_charles"
    assert src.source_code == "CCSO_MD_PD"
    assert src.source_state == "MD"


def test_wicomico_source_metadata() -> None:
    catalog = SourceCatalog.from_yaml("src/casesignal/etl/sources")
    src = catalog.get("cold_case_md_wicomico_2026_05_09")
    assert src.adapter_name == "cold_case_md_wicomico"
    assert src.source_code == "WICO_MD_SO"
    assert src.source_state == "MD"
