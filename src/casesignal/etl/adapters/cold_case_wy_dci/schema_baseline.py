"""Expected CSV column shape for the Wyoming DCI unified CSV.

Built by `scripts/build_wyoming_unified_csv.py` from the 3 Looker Studio
exports + the photo zip. Treat any deviation as a schema regression.
"""

from __future__ import annotations

COLD_CASE_WY_DCI_EXPECTED_COLUMNS: frozenset[str] = frozenset(
    [
        "source_case_id",
        "reported_date",
        "crime_types",
        "weapon",
        "victim_name",
        "victim_age",
        "victim_sex",
        "victim_race",
        "scene_type",
        "scene_address",
        "scene_business_name",
        "scene_city",
        "scene_county",
        "synopsis",
        "photo_filename",
    ]
)
