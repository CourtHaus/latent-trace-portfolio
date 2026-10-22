"""Adapter package for Harford County, MD Sheriff cold cases.

Single-page sheriff's-office WordPress site; ~21 unsolved cases
(1981-2021). Each case is an `<li>` item under `<ul class="subjects type-1">`
with a `<div class="img">` for the photo and `<div class="info">` containing
the victim name (h2) and narrative (p). Sheriff's Office, not PD — note
the source_code suffix _SO instead of _PD.
"""

from casesignal.etl.adapters.cold_case_md_harford.adapter import (
    ColdCaseMDHarfordAdapter,
)

__all__ = ["ColdCaseMDHarfordAdapter"]
