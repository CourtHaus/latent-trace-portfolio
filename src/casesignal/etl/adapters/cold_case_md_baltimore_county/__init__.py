"""Cold Case Maryland — Baltimore County PD adapter.

Scrapes the Baltimore County Government unsolved-homicides page
(https://www.baltimorecountymd.gov/departments/police/unsolved/homicides)
plus its detail pages, and ingests them as cold cases.

Phase 1 Architecture decision: this is one adapter for one county. When
Phase 1.5 adds a second MD county, common scraping helpers can be
extracted into a shared MD-county helpers module. Until then,
intentionally N=1.
"""

from casesignal.etl.adapters.cold_case_md_baltimore_county.adapter import (
    ColdCaseMDBaltimoreCountyAdapter,
)

__all__ = ["ColdCaseMDBaltimoreCountyAdapter"]
