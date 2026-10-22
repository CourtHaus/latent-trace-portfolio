#!/usr/bin/env bash
# sync_to_supabase.sh — Replace Supabase user-data with a snapshot of local
# Postgres. Source of truth is local; Supabase is fully replaceable.
#
# See docs/engineering-decisions.md for
# the design rationale and docs/deploy/runbook.md for the operator procedure.
#
# Exit codes:
#   0 success
#   1 pre-flight failed (env, host check, connectivity, alembic-not-at-head)
#   2 schema migration / API-surface harden step failed
#   3 data sync step failed
#   4 verification step failed
#  (photos step is non-fatal — failure is logged but does not change exit)

set -euo pipefail

DRY_RUN=0
AUTO_YES=0
WITH_PHOTOS=0
SKIP_SCHEMA=0

usage() {
  cat <<EOF
Usage: scripts/sync_to_supabase.sh [OPTIONS]

Replace Supabase user-data with a snapshot of local Postgres.

Required env (sourced from .env):
  DATABASE_URL              Local Postgres connection string
  SUPABASE_DATABASE_URL     Supabase Postgres connection string

Optional env (post-sync public-cache revalidation; skipped if unset):
  REVALIDATE_SECRET         Shared secret for the frontend /api/revalidate route
  NEXT_PUBLIC_SITE_URL      Public frontend origin (e.g. https://case-signal-zeta.vercel.app)
                            (or set REVALIDATE_URL to the full origin directly)

Options:
  --dry-run         Show what would change; do not touch Supabase
  --yes             Skip the interactive confirmation prompt
  --with-photos     Chain scripts/upload_photos_to_supabase_storage.py at end
  --skip-schema     Skip the alembic upgrade phase (Supabase already at head)
  -h, --help        Show this help and exit
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)     DRY_RUN=1; shift ;;
      --yes)         AUTO_YES=1; shift ;;
      --with-photos) WITH_PHOTOS=1; shift ;;
      --skip-schema) SKIP_SCHEMA=1; shift ;;
      -h|--help)     usage; exit 0 ;;
      *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
  done
}

fail_preflight() {
  echo "pre-flight: $1" >&2
  exit 1
}

phase_preflight() {
  echo "[1/6] pre-flight"

  # Source .env only if at least one required var is unset (not merely empty) —
  # preserves caller-injected env (used by the integration test) when both are
  # already in the environment, even if one was set to an empty string.
  if [[ -f .env && ( -z "${DATABASE_URL+x}" || -z "${SUPABASE_DATABASE_URL+x}" ) ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi

  [[ -n "${DATABASE_URL:-}" ]] || fail_preflight "DATABASE_URL is empty"
  [[ -n "${SUPABASE_DATABASE_URL:-}" ]] || fail_preflight "SUPABASE_DATABASE_URL is empty"
  [[ "$DATABASE_URL" != "$SUPABASE_DATABASE_URL" ]] \
    || fail_preflight "DATABASE_URL and SUPABASE_DATABASE_URL are identical — refusing to sync"

  if [[ "${CASESIGNAL_ALLOW_NON_SUPABASE_TARGET:-0}" != "1" ]]; then
    [[ "$SUPABASE_DATABASE_URL" == *supabase.co* ]] \
      || fail_preflight "SUPABASE_DATABASE_URL host does not contain 'supabase.co' (override with CASESIGNAL_ALLOW_NON_SUPABASE_TARGET=1 for tests)"
  fi

  # Connectivity
  pg_isready -d "$DATABASE_URL" >/dev/null \
    || fail_preflight "local Postgres (DATABASE_URL) is not reachable"
  pg_isready -d "$SUPABASE_DATABASE_URL" >/dev/null \
    || fail_preflight "target Postgres (SUPABASE_DATABASE_URL) is not reachable"

  # Test-seed guard. Integration tests run against the local DB (no separate
  # test database) and commit source_system rows like TEST_CODE / *_TEST /
  # FDLE_TRANSFORM_TEST; over many runs their orphan dataset_versions pile up.
  # The sync would faithfully push them to the public corpus. Refuse instead.
  # (Skipped under CASESIGNAL_ALLOW_NON_SUPABASE_TARGET=1 — the sync's own
  # integration test syncs deliberately-seeded data between ephemeral DBs.)
  if [[ "${CASESIGNAL_ALLOW_NON_SUPABASE_TARGET:-0}" != "1" ]]; then
    local test_sources
    test_sources=$(psql "$DATABASE_URL" -tA -c \
      "SELECT string_agg(source_code, ', ' ORDER BY source_code) FROM etl.source_system WHERE source_code ~* 'test|integration'" 2>/dev/null)
    if [[ -n "$test_sources" ]]; then
      fail_preflight "local DB has test-pattern source_system rows ($test_sources) — refusing to sync test data to production. Remove them first (see tools/clean_test_sources.py)."
    fi
  fi

  # Alembic head check on local
  local local_head
  local_head=$(DATABASE_URL="$DATABASE_URL" uv run alembic heads --resolve-dependencies 2>/dev/null | awk '{print $1}' | head -1)
  local local_current
  local_current=$(DATABASE_URL="$DATABASE_URL" uv run alembic current 2>/dev/null | awk '{print $1}' | head -1)
  [[ -n "$local_head" && "$local_current" == "$local_head"* ]] \
    || fail_preflight "local Postgres is not at alembic head (current=$local_current head=$local_head)"

  # Report Supabase's current revision (informational; phase 2 advances it)
  local supabase_current
  supabase_current=$(DATABASE_URL="$SUPABASE_DATABASE_URL" uv run alembic current 2>/dev/null | awk '{print $1}' | head -1)
  echo "  local head:        $local_head"
  echo "  supabase current:  ${supabase_current:-(no alembic_version)}"

  # Show row counts that will be replaced (one query per schema)
  echo "  target row counts to be replaced (current Supabase state):"
  for schema in cold_case etl raw_cold_case audit app_auth; do
    local total
    total=$(psql "$SUPABASE_DATABASE_URL" -tA -c "
      SELECT COALESCE(sum(n_live_tup)::bigint, 0)
        FROM pg_stat_user_tables
       WHERE schemaname = '$schema';
    " 2>/dev/null || echo 0)
    printf "    %-16s %s rows\n" "$schema" "$total"
  done

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] no changes will be made; exiting 0"
    exit 0
  fi

  if [[ "$AUTO_YES" -ne 1 ]]; then
    local host
    host=$(echo "$SUPABASE_DATABASE_URL" | sed -E 's|.*@([^:/]+).*|\1|')
    echo ""
    echo "About to REPLACE user-data on Supabase target:  $host"
    read -r -p "Proceed? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted by user"; exit 1; }
  fi
}

phase_schema() {
  echo "[2/6] schema upgrade"
  if ! DATABASE_URL="$SUPABASE_DATABASE_URL" uv run alembic upgrade head; then
    echo "schema migration failed" >&2
    exit 2
  fi
  # Verify post-upgrade
  local supabase_current local_head
  supabase_current=$(DATABASE_URL="$SUPABASE_DATABASE_URL" uv run alembic current 2>/dev/null | awk '{print $1}' | head -1)
  local_head=$(DATABASE_URL="$DATABASE_URL" uv run alembic heads --resolve-dependencies 2>/dev/null | awk '{print $1}' | head -1)
  if [[ "$supabase_current" != "$local_head"* ]]; then
    echo "post-upgrade rev ($supabase_current) does not match local head ($local_head)" >&2
    exit 2
  fi
  echo "  supabase now at:   $supabase_current"
}

phase_harden_api() {
  echo "[3/6] harden public API surface"
  # Lock down the PostgREST data surface that CaseSignal never uses: the
  # frontend uses Supabase for auth only, and all data flows through the
  # FastAPI service on a privileged connection that bypasses RLS. Two objects
  # in the API-exposed `public` schema keep getting flagged by the Supabase
  # linter, so we re-assert their lockdown on every sync. The block is
  # idempotent and tolerant of a vanilla (non-Supabase) target where the
  # anon/authenticated roles or the helper function don't exist:
  #   1. public.rls_auto_enable() — the dashboard's SECURITY DEFINER
  #      event-trigger helper. Revoke its (linter-flagged) RPC EXECUTE grant.
  #      This does NOT disable the event trigger: it fires as its owner via the
  #      event-trigger manager regardless of EXECUTE grants.
  #   2. public.alembic_version — migration bookkeeping that must never be
  #      reachable through /rest/v1.
  if ! psql "$SUPABASE_DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
DO $harden$
DECLARE
  role_name text;
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = 'rls_auto_enable'
  ) THEN
    EXECUTE 'REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC';
    FOR role_name IN SELECT unnest(ARRAY['anon', 'authenticated']) LOOP
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
        EXECUTE format('REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM %I', role_name);
      END IF;
    END LOOP;
  END IF;

  IF to_regclass('public.alembic_version') IS NOT NULL THEN
    -- PUBLIC first: every role inherits PUBLIC grants, so a stray GRANT … TO
    -- PUBLIC would otherwise leave the table reachable by anon/authenticated.
    EXECUTE 'REVOKE ALL ON TABLE public.alembic_version FROM PUBLIC';
    FOR role_name IN SELECT unnest(ARRAY['anon', 'authenticated']) LOOP
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
        EXECUTE format('REVOKE ALL ON TABLE public.alembic_version FROM %I', role_name);
      END IF;
    END LOOP;
  END IF;
END
$harden$;
SQL
  then
    echo "harden step failed" >&2
    exit 2
  fi
  echo "  ok — public RPC/table grants revoked from anon/authenticated/PUBLIC"
}

phase_verify() {
  echo "[5/6] verify"
  local schemas=(cold_case etl raw_cold_case audit app_auth)
  local mismatches=0
  for schema in "${schemas[@]}"; do
    # Iterate every table in the schema
    local tables
    tables=$(psql "$DATABASE_URL" -tA -c "
      SELECT tablename FROM pg_tables WHERE schemaname = '$schema' ORDER BY tablename;
    ")
    while IFS= read -r tbl; do
      [[ -z "$tbl" ]] && continue
      local src tgt
      src=$(psql "$DATABASE_URL"          -tA -c "SELECT count(*) FROM ${schema}.${tbl};" 2>/dev/null || echo "ERR")
      tgt=$(psql "$SUPABASE_DATABASE_URL" -tA -c "SELECT count(*) FROM ${schema}.${tbl};" 2>/dev/null || echo "ERR")
      if [[ "$src" != "$tgt" ]]; then
        echo "  MISMATCH ${schema}.${tbl}: local=$src target=$tgt" >&2
        mismatches=$((mismatches + 1))
      fi
    done <<< "$tables"
  done
  if [[ "$mismatches" -gt 0 ]]; then
    echo "verify failed: $mismatches table(s) had row count mismatch" >&2
    exit 4
  fi
  echo "  ok — all per-table row counts match"
}

phase_photos() {
  echo "[6/6] photos (optional)"
  if ! uv run python scripts/upload_photos_to_supabase_storage.py; then
    echo "  WARNING: photo upload returned non-zero; data sync remains committed" >&2
    echo "  re-run scripts/upload_photos_to_supabase_storage.py standalone to retry"
  else
    echo "  ok — photos uploaded"
  fi
}

phase_data_sync() {
  echo "[4/6] data sync"
  local dump_file wrapper_file raw_ddl_file
  dump_file=$(mktemp -t casesignal-sync-data.XXXXXX.sql)
  wrapper_file=$(mktemp -t casesignal-sync-wrap.XXXXXX.sql)
  raw_ddl_file=$(mktemp -t casesignal-sync-raw-ddl.XXXXXX.sql)
  # shellcheck disable=SC2064
  trap "rm -f '$dump_file' '$wrapper_file' '$raw_ddl_file'" EXIT

  echo "  dumping raw_cold_case schema DDL..."
  pg_dump "$DATABASE_URL" \
    --schema-only --no-owner --no-privileges --clean --if-exists \
    -n raw_cold_case \
    | grep -v '^DROP SCHEMA' \
    | grep -v '^CREATE SCHEMA' \
    > "$raw_ddl_file"

  echo "  dumping local data..."
  pg_dump "$DATABASE_URL" \
    --data-only --no-owner --no-privileges \
    -n cold_case -n etl -n raw_cold_case -n audit -n app_auth \
    > "$dump_file"

  # Extract the list of tables the dump touches (from COPY headers)
  local truncate_list
  truncate_list=$(grep -oE '^COPY [a-z_0-9]+\.[a-z_0-9]+' "$dump_file" \
                    | awk '{print $2}' \
                    | sort -u \
                    | paste -sd, -)

  if [[ -z "$truncate_list" ]]; then
    echo "  WARNING: dump contained zero COPY statements — local DB may be empty"
    echo "  proceeding with no TRUNCATE (nothing to clear)"
  fi

  echo "  building wrapper transaction..."
  {
    echo "BEGIN;"
    echo "SET session_replication_role = replica;"
    cat "$raw_ddl_file"
    if [[ -n "$truncate_list" ]]; then
      echo "TRUNCATE $truncate_list CASCADE;"
    fi
    cat "$dump_file"
    echo "SET session_replication_role = origin;"
    echo "COMMIT;"
  } > "$wrapper_file"

  echo "  loading into target..."
  # Safety: the wrapper contains DROP/TRUNCATE — apply ONLY to the target, never the source.
  [[ -n "$SUPABASE_DATABASE_URL" && "$SUPABASE_DATABASE_URL" != "$DATABASE_URL" ]] \
    || { echo "refusing to apply destructive wrapper: target invalid or equals source" >&2; exit 3; }
  if ! psql "$SUPABASE_DATABASE_URL" --single-transaction -v ON_ERROR_STOP=1 -f "$wrapper_file" >/dev/null; then
    echo "data sync failed (psql returned non-zero); transaction rolled back" >&2
    exit 3
  fi

  local table_count
  table_count=$(echo "$truncate_list" | awk -F, '{print NF}')
  echo "  ok — replaced $table_count tables on target"
}

phase_revalidate() {
  echo "[revalidate] purge public cache"
  local url="${REVALIDATE_URL:-${NEXT_PUBLIC_SITE_URL:-}}"
  if [[ -z "${REVALIDATE_SECRET:-}" || -z "$url" ]]; then
    echo "  SKIPPED — set REVALIDATE_SECRET + NEXT_PUBLIC_SITE_URL (or REVALIDATE_URL) to enable"
    return 0
  fi
  url="${url%/}/api/revalidate"
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
    -X POST -H "x-revalidate-secret: ${REVALIDATE_SECRET}" "$url" || echo "000")
  if [[ "$code" == "200" ]]; then
    echo "  ok — public cache revalidated"
  else
    echo "  WARNING: revalidate POST to $url returned HTTP $code; data is synced but the public site may lag up to 1h" >&2
  fi
  return 0
}

main() {
  parse_args "$@"
  phase_preflight

  if [[ "$SKIP_SCHEMA" -ne 1 ]]; then
    phase_schema
  else
    echo "[2/6] schema upgrade  — SKIPPED (--skip-schema)"
  fi

  # Always runs (incl. --skip-schema): idempotent grant lockdown of the unused
  # PostgREST surface. Cheap and safe even when nothing changed.
  phase_harden_api

  phase_data_sync
  phase_verify
  if [[ "$WITH_PHOTOS" -eq 1 ]]; then
    phase_photos
  fi
  phase_revalidate
  echo "done"
  exit 0
}

main "$@"
