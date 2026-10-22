"""Adapter package for Howard County, MD PD cold cases.

Single-page county-government site; ~24 unsolved cases (plus 3 SOLVED
cases shown for context that we filter out). Each section: heading of
form `Homicide of <Name>, <date>`, narrative paragraphs, optional photo.
"""

from casesignal.etl.adapters.cold_case_md_howard.adapter import (
    ColdCaseMDHowardAdapter,
)

__all__ = ["ColdCaseMDHowardAdapter"]
