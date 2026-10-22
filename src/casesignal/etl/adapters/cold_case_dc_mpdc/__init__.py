"""Adapter package for Washington D.C. Metropolitan Police Department
unsolved homicides.

Multi-page scrape: hub → year-page → detail-page → PDF flier. PDF
parsing extracts case number (CCN), victim photo, detective contacts,
and reward amount from the official MPDC reward bulletin layout.

Tier-2 LLM extraction is skipped for DC (narratives are too sparse to
justify the compute); gender is extracted via regex on honorifics
in transform.
"""

from casesignal.etl.adapters.cold_case_dc_mpdc.adapter import (
    ColdCaseDCMPDCAdapter,
)

__all__ = ["ColdCaseDCMPDCAdapter"]
