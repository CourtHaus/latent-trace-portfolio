"""Trusted pytest startup hook: confine before importing any generated module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from casesignal.drafter.sandbox import IsolationUnavailable, confine


def pytest_sessionstart(session: pytest.Session) -> None:
    try:
        confine(Path.cwd(), Path(os.environ["TMPDIR"]))
    except IsolationUnavailable as exc:
        raise pytest.UsageError(f"grading isolation unavailable: {exc}") from exc
