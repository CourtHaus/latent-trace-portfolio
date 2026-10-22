#!/usr/bin/env bash
# Integration test for scripts/sync_to_supabase.sh.
# Spins up two ephemeral Postgres containers (source + target), seeds the
# source with alembic head + minimal fixtures, runs the sync script against
# them, asserts the target matches. Tears down on exit (always).
#
# Run:  tests/integration/test_sync_to_supabase.sh
# Requires: docker, bash 5+, and the project's uv-managed Python env for alembic.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SOURCE_PORT=5444
TARGET_PORT=5445
SOURCE_NAME="casesignal-sync-test-source"
TARGET_NAME="casesignal-sync-test-target"
PG_IMAGE="postgis/postgis:16-3.5"
PG_PASS="testpass"

SOURCE_URL="postgresql://postgres:${PG_PASS}@127.0.0.1:${SOURCE_PORT}/postgres"
TARGET_URL="postgresql://postgres:${PG_PASS}@127.0.0.1:${TARGET_PORT}/postgres"

PASS=0
FAIL=0

note()   { echo "[test] $*"; }
ok()     { echo "[ OK ] $*"; PASS=$((PASS+1)); }
bad()    { echo "[FAIL] $*"; FAIL=$((FAIL+1)); }

teardown() {
  note "teardown"
  docker rm -f "$SOURCE_NAME" "$TARGET_NAME" >/dev/null 2>&1 || true
}
trap teardown EXIT

start_pg() {
  local name="$1" port="$2"
  docker run -d --rm --name "$name" \
    -e POSTGRES_PASSWORD="$PG_PASS" \
    -p "${port}:5432" \
    "$PG_IMAGE" >/dev/null
}

wait_pg() {
  local url="$1"
  for _ in $(seq 1 30); do
    if PGPASSWORD="$PG_PASS" psql "$url" -tA -c "SELECT 1" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

count_rows() {
  local url="$1" table="$2"
  PGPASSWORD="$PG_PASS" psql "$url" -tA -c "SELECT count(*) FROM ${table};" 2>/dev/null
}

main() {
  note "starting ephemeral Postgres containers (source=${SOURCE_PORT}, target=${TARGET_PORT})"
  start_pg "$SOURCE_NAME" "$SOURCE_PORT"
  start_pg "$TARGET_NAME" "$TARGET_PORT"

  wait_pg "$SOURCE_URL" || { bad "source pg never came up"; exit 1; }
  wait_pg "$TARGET_URL" || { bad "target pg never came up"; exit 1; }
  ok "both postgres containers ready"

  # Reproduce the Supabase API-surface findings on the TARGET so the harden
  # phase has something to revoke: a SECURITY DEFINER event-trigger helper
  # (public.rls_auto_enable) callable by anon/authenticated/PUBLIC, plus the
  # anon/authenticated roles themselves. (alembic_version is created later by
  # the sync's schema phase; its grant drift is induced before the re-sync.)
  note "seeding TARGET with a SECURITY DEFINER rls_auto_enable + supabase roles"
  PGPASSWORD="$PG_PASS" psql "$TARGET_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
    DO $seed$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
    END $seed$;
    CREATE OR REPLACE FUNCTION public.rls_auto_enable()
      RETURNS event_trigger LANGUAGE plpgsql SECURITY DEFINER AS $fn$ BEGIN NULL; END $fn$;
    GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO anon, authenticated;
SQL
  ok "target seeded with rls_auto_enable + anon/authenticated"

  note "applying alembic head to source"
  cd "$REPO_ROOT"
  DATABASE_URL="$SOURCE_URL" uv run alembic upgrade head >/dev/null
  ok "source at alembic head"

  note "pre-flight: missing SUPABASE_DATABASE_URL should fail"
  if DATABASE_URL="$SOURCE_URL" SUPABASE_DATABASE_URL="" \
       "$REPO_ROOT/scripts/sync_to_supabase.sh" --yes 2>/dev/null; then
    bad "expected exit 1 when SUPABASE_DATABASE_URL empty"
  else
    ok "pre-flight rejects empty SUPABASE_DATABASE_URL"
  fi

  note "pre-flight: same URL for both should fail"
  if DATABASE_URL="$SOURCE_URL" SUPABASE_DATABASE_URL="$SOURCE_URL" \
       "$REPO_ROOT/scripts/sync_to_supabase.sh" --yes 2>/dev/null; then
    bad "expected exit 1 when DATABASE_URL == SUPABASE_DATABASE_URL"
  else
    ok "pre-flight rejects same-URL config"
  fi

  note "pre-flight: non-supabase host without override should fail"
  if DATABASE_URL="$SOURCE_URL" SUPABASE_DATABASE_URL="$TARGET_URL" \
       "$REPO_ROOT/scripts/sync_to_supabase.sh" --yes 2>/dev/null; then
    bad "expected exit 1 when SUPABASE_DATABASE_URL host lacks supabase.co"
  else
    ok "pre-flight rejects non-supabase host without override"
  fi

  note "seeding source with a minimal cold-case row"
  PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
    WITH dv AS (
      INSERT INTO etl.dataset_version
        (source_system_id, source_year, source_label, source_hash, ingestion_status)
      SELECT source_system_id, 2026, 'Sync Test DV', md5('sync-test'), 'published'
      FROM etl.source_system WHERE source_code = 'TEST_CODE'
      RETURNING dataset_version_id
    )
    INSERT INTO cold_case.cases
      (dataset_version_id, source_case_id, slug, case_name, case_type, state, about_text)
    SELECT dv.dataset_version_id,
           'TEST-001', 'sync-test-case', 'Sync Test Case', 'homicide', 'ZZ',
           'Test fixture for sync workflow.'
    FROM dv;
SQL
  ok "source seeded with 1 row in cold_case.cases"

  note "seeding source with a raw_cold_case table mimicking adapter pattern"
  PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
    CREATE TABLE raw_cold_case.test_sync_dv1 (
      dataset_version_id INTEGER NOT NULL,
      source_case_id     TEXT NOT NULL,
      raw_payload        TEXT,
      PRIMARY KEY (dataset_version_id, source_case_id)
    );
    INSERT INTO raw_cold_case.test_sync_dv1 (dataset_version_id, source_case_id, raw_payload)
    SELECT dataset_version_id, 'RAW-001', '{"test":"raw_fixture"}'
      FROM etl.dataset_version
     LIMIT 1;
SQL
  ok "source raw_cold_case.test_sync_dv1 created with 1 row"

  # Snapshot source state before sync — used below to assert source is never mutated.
  local src_raw_tables_before src_cold_counts_before
  src_raw_tables_before=$(PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -tA \
    -c "SELECT tablename FROM pg_tables WHERE schemaname='raw_cold_case' ORDER BY tablename;")
  src_cold_counts_before=$(PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -tA \
    -c "SELECT tablename, (xpath('/row/cnt/text()', query_to_xml('SELECT count(*) AS cnt FROM cold_case.'||tablename, false, false, '')))[1]::text
        FROM pg_tables WHERE schemaname='cold_case' ORDER BY tablename;" 2>/dev/null \
    || PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -tA \
    -c "SELECT 'cases', count(*) FROM cold_case.cases;")

  note "running sync script (--yes)"
  CASESIGNAL_ALLOW_NON_SUPABASE_TARGET=1 \
    DATABASE_URL="$SOURCE_URL" \
    SUPABASE_DATABASE_URL="$TARGET_URL" \
    "$REPO_ROOT/scripts/sync_to_supabase.sh" --yes \
    || { bad "sync script returned non-zero"; exit 1; }

  # Assert source was NOT mutated by the sync.
  local src_raw_tables_after src_cold_counts_after
  src_raw_tables_after=$(PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -tA \
    -c "SELECT tablename FROM pg_tables WHERE schemaname='raw_cold_case' ORDER BY tablename;")
  src_cold_counts_after=$(PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -tA \
    -c "SELECT tablename, (xpath('/row/cnt/text()', query_to_xml('SELECT count(*) AS cnt FROM cold_case.'||tablename, false, false, '')))[1]::text
        FROM pg_tables WHERE schemaname='cold_case' ORDER BY tablename;" 2>/dev/null \
    || PGPASSWORD="$PG_PASS" psql "$SOURCE_URL" -tA \
    -c "SELECT 'cases', count(*) FROM cold_case.cases;")
  if [[ "$src_raw_tables_before" == "$src_raw_tables_after" ]]; then
    ok "source raw_cold_case table list unchanged after sync"
  else
    bad "FAIL: sync mutated SOURCE raw_cold_case table list"
    echo "  before: $src_raw_tables_before" >&2
    echo "  after:  $src_raw_tables_after" >&2
    exit 1
  fi
  if [[ "$src_cold_counts_before" == "$src_cold_counts_after" ]]; then
    ok "source cold_case row counts unchanged after sync"
  else
    bad "FAIL: sync mutated SOURCE cold_case row counts"
    echo "  before: $src_cold_counts_before" >&2
    echo "  after:  $src_cold_counts_after" >&2
    exit 1
  fi

  local src_count tgt_count raw_src raw_tgt
  src_count=$(count_rows "$SOURCE_URL" "cold_case.cases")
  tgt_count=$(count_rows "$TARGET_URL" "cold_case.cases")
  if [[ "$src_count" == "$tgt_count" && "$tgt_count" == "1" ]]; then
    ok "target cold_case.cases count matches source ($tgt_count)"
  else
    bad "row count mismatch: source=${src_count} target=${tgt_count}"
  fi

  raw_src=$(count_rows "$SOURCE_URL" "raw_cold_case.test_sync_dv1")
  raw_tgt=$(count_rows "$TARGET_URL" "raw_cold_case.test_sync_dv1")
  if [[ "$raw_src" == "$raw_tgt" && "$raw_tgt" == "1" ]]; then
    ok "target raw_cold_case.test_sync_dv1 count matches source ($raw_tgt)"
  else
    bad "raw_cold_case row count mismatch: source=${raw_src} target=${raw_tgt}"
  fi

  # API-surface hardening (SEC: SECURITY DEFINER RPC exposure). The harden phase
  # must have stripped EXECUTE on rls_auto_enable from anon/authenticated/PUBLIC.
  local fn_grants
  fn_grants=$(PGPASSWORD="$PG_PASS" psql "$TARGET_URL" -tA -c \
    "SELECT count(*) FROM information_schema.routine_privileges
      WHERE routine_schema='public' AND routine_name='rls_auto_enable'
        AND grantee IN ('anon','authenticated','PUBLIC') AND privilege_type='EXECUTE';")
  if [[ "$fn_grants" == "0" ]]; then
    ok "harden: rls_auto_enable EXECUTE revoked from anon/authenticated/PUBLIC"
  else
    bad "harden: rls_auto_enable still EXECUTE-able by ${fn_grants} role(s)"
  fi

  note "idempotency: re-run sync after inducing drift on target"
  PGPASSWORD="$PG_PASS" psql "$TARGET_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
    WITH dv AS (
      INSERT INTO etl.dataset_version (source_system_id, source_year, source_label, source_hash, ingestion_status)
      SELECT source_system_id, 2026, 'Drift Test DV', md5('drift-test'), 'published'
      FROM etl.source_system WHERE source_code = 'TEST_CODE'
      RETURNING dataset_version_id
    )
    INSERT INTO cold_case.cases (source_case_id, state, case_name, about_text, case_type, dataset_version_id, slug)
    SELECT 'TEST-DRIFT', 'ZZ', 'Drift Inducer', 'Force verify mismatch.', 'homicide', dataset_version_id, 'drift-inducer'
      FROM dv;
SQL

  # alembic_version exists now (created by the first sync's schema phase). Grant
  # both a direct anon grant AND a PUBLIC grant (which every role inherits) so
  # the next sync's harden phase has both paths to revoke.
  note "inducing alembic_version anon + PUBLIC grant drift on target before re-sync"
  PGPASSWORD="$PG_PASS" psql "$TARGET_URL" -v ON_ERROR_STOP=1 \
    -c "GRANT SELECT ON public.alembic_version TO anon, PUBLIC;" >/dev/null

  # Re-run the whole sync; the data phase will TRUNCATE+restore so target matches
  # source again. This proves the sync is idempotent.
  CASESIGNAL_ALLOW_NON_SUPABASE_TARGET=1 \
    DATABASE_URL="$SOURCE_URL" \
    SUPABASE_DATABASE_URL="$TARGET_URL" \
    "$REPO_ROOT/scripts/sync_to_supabase.sh" --yes --skip-schema \
    || { bad "second sync (idempotency check) returned non-zero"; }

  src_count=$(count_rows "$SOURCE_URL" "cold_case.cases")
  tgt_count=$(count_rows "$TARGET_URL" "cold_case.cases")
  if [[ "$src_count" == "$tgt_count" && "$tgt_count" == "1" ]]; then
    ok "idempotent: re-sync after drift restored target to match source ($tgt_count)"
  else
    bad "idempotency check failed: source=${src_count} target=${tgt_count}"
  fi

  raw_tgt=$(count_rows "$TARGET_URL" "raw_cold_case.test_sync_dv1")
  if [[ "$raw_tgt" == "1" ]]; then
    ok "idempotent: raw_cold_case row preserved after re-sync (1)"
  else
    bad "idempotent raw_cold_case lost: target=${raw_tgt}"
  fi

  # The re-sync's harden phase must have revoked the alembic_version grant we
  # induced above (proves harden runs on every sync, incl. --skip-schema).
  local av_grants
  av_grants=$(PGPASSWORD="$PG_PASS" psql "$TARGET_URL" -tA -c \
    "SELECT count(*) FROM information_schema.role_table_grants
      WHERE table_schema='public' AND table_name='alembic_version'
        AND grantee IN ('anon','authenticated','PUBLIC');")
  if [[ "$av_grants" == "0" ]]; then
    ok "harden: alembic_version grants revoked from anon/authenticated/PUBLIC after re-sync"
  else
    bad "harden: alembic_version still has ${av_grants} anon/authenticated/PUBLIC grant(s)"
  fi

  echo ""
  echo "=== test summary: ${PASS} passed, ${FAIL} failed ==="
  [[ "$FAIL" -eq 0 ]]
}

main "$@"
