"""Column baseline for VA cold case CSV ingestion.

Columns are captured from the 2025-03-27 VSPCCD extract. The CSV ships UTF-8
with a BOM on the first column name ("﻿_id") — strip the BOM before
comparing against this set.

If a future extract has new columns, extend this set. If columns are removed,
decide per-column whether to treat as blocking or warning.
"""

from __future__ import annotations

COLD_CASE_VA_EXPECTED_COLUMNS: frozenset[str] = frozenset(
    {
        "_id",
        "case_name",
        "post_id",
        "type",
        "incident-date",
        "address",
        "city",
        "state",
        "vspccd-number",
        "about",
        "victim-fields_first-name",
        "victim-fields_last-name",
        "victim-fields_gender",
        "victim-fields_height",
        "victim-fields_weight",
        "victim-fields_age",
        "victim-fields_race",
        "victim-fields_eye-color",
        "victim-fields_hair-color",
        "contact-first-name",
        "contact-last-name",
        "contact-phone-number",
        "contact-address",
        "contact-email",
        "geographic-location",
    }
)
