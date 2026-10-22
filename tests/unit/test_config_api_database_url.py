"""Settings exposes API_DATABASE_URL (pooled URL for the API only)."""

from __future__ import annotations

import importlib

from pytest import MonkeyPatch


def test_api_database_url_defaults_empty(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("API_DATABASE_URL", raising=False)
    import casesignal.etl.config as config

    importlib.reload(config)
    assert config.settings.api_database_url == ""


def test_api_database_url_read_from_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("API_DATABASE_URL", "postgresql+psycopg2://u:p@h:6543/db")
    import casesignal.etl.config as config

    importlib.reload(config)
    assert config.settings.api_database_url == "postgresql+psycopg2://u:p@h:6543/db"
