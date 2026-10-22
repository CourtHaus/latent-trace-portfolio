"""Rate-limiter storage selection: memory by default, Redis when configured,
always fail-open (swallow_errors)."""

from __future__ import annotations

import pytest

from casesignal.api.middleware import rate_limit


def test_kwargs_default_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_REDIS_URL", raising=False)
    kw = rate_limit._limiter_kwargs()
    assert "storage_uri" not in kw
    assert kw["swallow_errors"] is True
    assert kw["default_limits"] == ["120/minute"]


def test_kwargs_use_redis_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REDIS_URL", "rediss://default:pw@host:6379")
    kw = rate_limit._limiter_kwargs()
    assert kw["storage_uri"] == "rediss://default:pw@host:6379"
    assert kw["swallow_errors"] is True
    assert kw["default_limits"] == ["120/minute"]


def test_blank_redis_url_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REDIS_URL", "   ")
    kw = rate_limit._limiter_kwargs()
    assert "storage_uri" not in kw
