from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Settings:
    database_url: str
    api_database_url: str = ""
    app_env: str = "production"
    sqlalchemy_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout_seconds: int = 30
    database_statement_timeout_ms: int = 30000
    database_lock_timeout_ms: int = 30000
    database_application_name: str = "casesignal_etl"
    log_level: str = "INFO"
    key_hmac_secret: str = ""


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int, min_value: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    parsed = int(value.strip())
    if parsed < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {parsed}")
    return parsed


settings = Settings(
    database_url=os.getenv("DATABASE_URL", ""),
    api_database_url=os.getenv("API_DATABASE_URL", ""),
    app_env=os.getenv("APP_ENV", "production"),
    sqlalchemy_echo=_get_bool_env("SQLALCHEMY_ECHO", default=False),
    database_pool_size=_get_int_env("DATABASE_POOL_SIZE", default=5, min_value=1),
    database_max_overflow=_get_int_env("DATABASE_MAX_OVERFLOW", default=10, min_value=1),
    database_pool_timeout_seconds=_get_int_env(
        "DATABASE_POOL_TIMEOUT_SECONDS", default=30, min_value=1
    ),
    database_statement_timeout_ms=_get_int_env(
        "DATABASE_STATEMENT_TIMEOUT_MS", default=30000, min_value=0
    ),
    database_lock_timeout_ms=_get_int_env("DATABASE_LOCK_TIMEOUT_MS", default=30000, min_value=0),
    database_application_name=os.getenv("DATABASE_APPLICATION_NAME", "casesignal_etl"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    key_hmac_secret=os.getenv("KEY_HMAC_SECRET", ""),
)

_database_url_explicitly_set = os.getenv("DATABASE_URL") is not None

if settings.app_env != "dev" and not _database_url_explicitly_set:
    raise RuntimeError(
        "DATABASE_URL must be set explicitly in non-dev environments. "
        "Set APP_ENV=dev to suppress this check during local development."
    )

if settings.app_env != "dev" and not settings.key_hmac_secret:
    raise RuntimeError(
        "KEY_HMAC_SECRET must be set in non-dev environments. "
        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
    )
