"""Defense-in-depth: CaseContactSection rejects detective name fields.

The SQL layer in services/cold_cases.py already omits first_name/last_name
from the SELECT. This test pins the second line of defense: even if a future
refactor forgets and includes them, Pydantic's extra='forbid' raises loudly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from casesignal.api.schemas.cold_cases import CaseContactSection


def test_case_contact_section_rejects_first_name() -> None:
    with pytest.raises(ValidationError):
        CaseContactSection(
            phone="(555) 123-4567",
            email=None,
            address=None,
            first_name="Leaked Name",  # type: ignore[call-arg]
        )


def test_case_contact_section_rejects_last_name() -> None:
    with pytest.raises(ValidationError):
        CaseContactSection(
            phone="(555) 123-4567",
            email=None,
            address=None,
            last_name="Leaked Surname",  # type: ignore[call-arg]
        )


def test_case_contact_section_accepts_valid_fields() -> None:
    """Sanity: the three allowed fields pass validation."""
    c = CaseContactSection(
        phone="(555) 123-4567",
        email="tips@agency.gov",
        address="123 Main St",
    )
    assert c.phone == "(555) 123-4567"
    assert c.email == "tips@agency.gov"
    assert c.address == "123 Main St"
