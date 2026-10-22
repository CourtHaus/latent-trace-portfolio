"""Adapter package for Colorado Bureau of Investigation (CBI) cold-case database.

State compendium of HOMICIDE+OPEN cases submitted by 86 county/municipal
agencies. Live POST-paginated search at apps.colorado.gov, with rich
per-case detail pages publishing ~20 structured fields.

Tier-2 LLM extraction is intentionally NOT used — CBI publishes Gender,
Race, Age, Ethnicity directly. Honorific-based gender extraction is also
not used (unlike DC).
"""

from casesignal.etl.adapters.cold_case_co.adapter import ColdCaseCOAdapter

__all__ = ["ColdCaseCOAdapter"]
