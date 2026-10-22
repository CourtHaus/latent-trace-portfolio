#!/usr/bin/env bash
# Create + migrate + stamp the local CaseSignal TEST database. Idempotent.
# Mirrors CI (no seed load; integration tests seed their own corpora).
# NEVER touches the live `casesignal` database.
set -euo pipefail

HOST="${TEST_DB_HOST:-localhost}"
PORT="${TEST_DB_PORT:-5433}"
DBUSER="${TEST_DB_USER:-casesignal}"
DBPW="${TEST_DB_PASSWORD:-casesignal}"
TESTDB="${TEST_DB_NAME:-casesignal_test}"

if [ "$TESTDB" = "casesignal" ]; then
  echo "Refusing to operate on the live database 'casesignal'." >&2
  exit 1
fi

export PGPASSWORD="$DBPW"
ADMIN="postgresql://${DBUSER}:${DBPW}@${HOST}:${PORT}/postgres"
TESTDB_PSQL="postgresql://${DBUSER}:${DBPW}@${HOST}:${PORT}/${TESTDB}"
TESTDB_SA="postgresql+psycopg2://${DBUSER}:${DBPW}@${HOST}:${PORT}/${TESTDB}"

echo "==> Ensuring database ${TESTDB} exists"
if ! psql "$ADMIN" -tAc "SELECT 1 FROM pg_database WHERE datname='${TESTDB}'" | grep -q 1; then
  psql "$ADMIN" -c "CREATE DATABASE ${TESTDB}"
fi

echo "==> Applying migrations to ${TESTDB}"
DATABASE_URL="$TESTDB_SA" APP_ENV=test KEY_HMAC_SECRET=test-hmac-secret \
  uv run alembic upgrade head

echo "==> Stamping sentinel"
# Sentinel table name is the contract with the pytest guard; keep in sync with
# SENTINEL_TABLE in tests/support/db_guard.py (and the CI stamp step in ci.yaml).
psql "$TESTDB_PSQL" -c "CREATE TABLE IF NOT EXISTS public._casesignal_test_sentinel ()"

echo "==> ${TESTDB} ready (migrated + sentinel stamped)."
