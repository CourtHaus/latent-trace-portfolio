"""Adapter package for Utah Bureau of Criminal Identification (BCI) cold cases.

State compendium of cold cases statutorily mandated by Utah SB 160 (2018) —
every Utah law enforcement agency must submit cases unsolved ≥3 years.
Enumeration is a single WordPress sitemap GET (~497 entries, all case types);
homicide-only filter is applied at detail-parse time.

Tier-2 LLM extraction is intentionally NOT used — BCI publishes Gender, Race,
Ethnicity, and DOB as structured fields where present. Tier-1 weapon and
location-type extraction is still run against the narrative paragraph.
"""

from casesignal.etl.adapters.cold_case_ut.adapter import ColdCaseUTAdapter

__all__ = ["ColdCaseUTAdapter"]
