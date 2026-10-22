"""Adapter package for Anne Arundel County, MD PD cold cases.

Single-page Drupal site at /police-department/crime-information/cold-cases.
~75 h3-anchored victim sections per page, each containing a narrative
that explicitly states case number, age, race, gender, and location.
"""

from casesignal.etl.adapters.cold_case_md_anne_arundel.adapter import (
    ColdCaseMDAnneArundelAdapter,
)

__all__ = ["ColdCaseMDAnneArundelAdapter"]
