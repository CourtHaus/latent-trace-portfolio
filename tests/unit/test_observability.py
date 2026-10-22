"""Unit tests for casesignal.observability (Sentry wiring).

These never touch a real Sentry account: the DSN-less paths are genuine no-ops,
and the active paths monkeypatch the sentry_sdk entry points.
"""

from __future__ import annotations

import pytest
import sentry_sdk
import sentry_sdk.crons

from casesignal import observability


def _reset_state() -> None:
    observability._initialized = False
    observability._last_checkin = 0.0


def test_init_sentry_noop_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    called = False

    def _fake_init(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(sentry_sdk, "init", _fake_init)

    assert observability.init_sentry("api") is False
    assert called is False
    assert observability._initialized is False


def test_init_sentry_initializes_with_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/1")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    captured: dict[str, object] = {}

    def _fake_init(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", _fake_init)
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a, **k: None)

    assert observability.init_sentry("api") is True
    assert observability._initialized is True
    assert str(captured["dsn"]).endswith("/1")
    assert captured["environment"] == "dev"
    # Sensitive-data platform: PII must never be attached by default.
    assert captured["send_default_pii"] is False


def test_init_sentry_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/1")
    calls = 0

    def _fake_init(**kwargs: object) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(sentry_sdk, "init", _fake_init)
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a, **k: None)

    assert observability.init_sentry("api") is True
    assert observability.init_sentry("api") is True
    assert calls == 1  # second call short-circuits


def test_heartbeat_noop_when_not_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    monkeypatch.setenv("SENTRY_WORKER_MONITOR_SLUG", "extraction-worker")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        sentry_sdk.crons, "capture_checkin", lambda **k: calls.append(k)
    )

    observability.worker_heartbeat()
    assert calls == []


def test_heartbeat_noop_without_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    observability._initialized = True
    monkeypatch.delenv("SENTRY_WORKER_MONITOR_SLUG", raising=False)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        sentry_sdk.crons, "capture_checkin", lambda **k: calls.append(k)
    )

    observability.worker_heartbeat()
    assert calls == []


def test_heartbeat_checks_in_and_throttles(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    observability._initialized = True
    monkeypatch.setenv("SENTRY_WORKER_MONITOR_SLUG", "extraction-worker")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        sentry_sdk.crons, "capture_checkin", lambda **k: calls.append(k)
    )

    # First call fires; an immediate second call is throttled away.
    observability.worker_heartbeat(min_interval_seconds=1000)
    observability.worker_heartbeat(min_interval_seconds=1000)

    assert len(calls) == 1
    assert calls[0]["monitor_slug"] == "extraction-worker"
    assert calls[0]["status"] == "ok"
    config = calls[0]["monitor_config"]
    assert isinstance(config, dict)
    assert config["schedule"]["type"] == "interval"
