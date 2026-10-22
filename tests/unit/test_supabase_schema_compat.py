from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OPERATIONAL_FILES = [
    "migrations/versions/0001_baseline.py",
    "migrations/versions/0009_drop_api_keys_key_hash.py",
    "scripts/create_api_key.py",
    "src/casesignal/api/dependencies/auth.py",
    "src/casesignal/api/routes/admin/keys.py",
    "tests/integration/test_admin_keys.py",
    "tests/integration/security/conftest.py",
    "tests/integration/security/test_key_hmac_migration.py",
    "tests/integration/security/test_key_lifecycle.py",
]

RESERVED_AUTH_SCHEMA_PATTERNS = {
    "auth.api_keys": re.compile(r"(?<!app_)auth\.api_keys"),
    "CREATE SCHEMA IF NOT EXISTS auth": re.compile(r"CREATE SCHEMA IF NOT EXISTS auth\b"),
    "DROP SCHEMA IF EXISTS auth": re.compile(r"DROP SCHEMA IF EXISTS auth\b"),
    'schema="auth"': re.compile(r'schema="auth"'),
}


def test_api_key_tables_do_not_use_supabase_reserved_auth_schema() -> None:
    offenders: list[str] = []

    for relative_path in OPERATIONAL_FILES:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for label, pattern in RESERVED_AUTH_SCHEMA_PATTERNS.items():
            if pattern.search(text):
                offenders.append(f"{relative_path}: {label}")

    assert offenders == []
