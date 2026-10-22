#!/usr/bin/env bash
#
# Off-site backup of the Latent Trace corpus to Google Cloud Storage.
#
# Backs up the two irreplaceable assets:
#   1. The Postgres database (extraction work, case data) as a compressed,
#      custom-format pg_dump.
#   2. The local photos directory (gitignored, expensive-to-impossible to
#      re-scrape) via incremental rsync.
#
# pg_dump takes an MVCC-consistent snapshot, so this is READ-ONLY against the
# live DB and safe to run while the extraction worker is writing.
#
# Every run CHECKS the dump archive directory (pg_restore --list) before trusting
# it. A separate restore drill is still required. On any failure the script exits
# non-zero with a `BACKUP_FAILED:` line so a scheduler/alert can catch it.
#
# Usage:
#   scripts/backup_corpus.sh
#
# Config (env overrides; sensible defaults):
#   BACKUP_BUCKET   gs:// target            (required; no production default)
#   DATABASE_URL    source DSN              (read from .env if unset)
#   PHOTOS_DIR      local photos path       (default: CASESIGNAL_PHOTOS_ROOT, else data/photos)
#   BACKUP_WORKDIR  local scratch for dumps (default: $HOME/casesignal-backups)
#
# Retention is enforced by the bucket lifecycle policy (see docs/RESTORE.md),
# not by this script, so a missed run never deletes the only good copy.

set -euo pipefail

umask 077
WORKDIR="${BACKUP_WORKDIR:-$HOME/casesignal-backups}"
LOCAL_KEEP=7  # local dump copies to retain; cloud retention is the lifecycle's job

fail() { echo "BACKUP_FAILED: $*" >&2; exit 1; }

# Load .env so DATABASE_URL and CASESIGNAL_PHOTOS_ROOT are present when a
# scheduled task runs without an inherited environment. SOURCE it (don't grep)
# so the checked-in template's ${POSTGRES_USER}/${POSTGRES_PASSWORD}
# interpolation expands, matching scripts/sync_to_supabase.sh.
if [ -z "${DATABASE_URL:-}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ENV_FILE="$SCRIPT_DIR/../.env"
  # shellcheck disable=SC1090,SC1091
  [ -f "$ENV_FILE" ] && source "$ENV_FILE"
fi
[ -n "${BACKUP_BUCKET:-}" ] || fail "set BACKUP_BUCKET to your private gs:// bucket"
[[ "$BACKUP_BUCKET" == gs://?* ]] || fail "BACKUP_BUCKET must be a gs:// destination"
DSN="${DATABASE_URL:-}"
DSN="${DSN/postgresql+psycopg2:/postgresql:}"
[ -n "$DSN" ] || fail "no DSN (set DATABASE_URL or add it to .env)"

# Photos root: honor the codebase-wide CASESIGNAL_PHOTOS_ROOT (see
# docs/deploy/runbook.md) so we back up the exact directory the app reads from,
# not a stale ./data/photos. PHOTOS_DIR still overrides for ad-hoc runs.
PHOTOS_DIR="${PHOTOS_DIR:-${CASESIGNAL_PHOTOS_ROOT:-data/photos}}"

command -v pg_dump   >/dev/null 2>&1 || fail "pg_dump not on PATH"
command -v pg_restore >/dev/null 2>&1 || fail "pg_restore not on PATH"
command -v gcloud    >/dev/null 2>&1 || fail "gcloud not on PATH"

mkdir -p "$WORKDIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="$WORKDIR/casesignal_${TS}.dump"

echo "[$TS] dumping database ..."
pg_dump "$DSN" -Fc -f "$DUMP" || fail "pg_dump failed"

echo "[$TS] checking dump archive directory ..."
pg_restore --list "$DUMP" >/dev/null 2>&1 || fail "dump unreadable (pg_restore --list)"
# Crown-jewel sanity: the authoritative extraction table must be in the dump.
pg_restore --list "$DUMP" | grep "TABLE DATA cold_case case_extractions" >/dev/null \
  || fail "dump is missing cold_case.case_extractions"

echo "[$TS] uploading database dump ..."
gcloud storage cp "$DUMP" "$BACKUP_BUCKET/db/" || fail "db dump upload failed"

# A backup that silently omits the irreplaceable photo corpus while reporting
# success is worse than no backup. If the resolved dir is missing, fail loudly
# rather than emit BACKUP_OK without photos.
[ -d "$PHOTOS_DIR" ] || fail "photos dir '$PHOTOS_DIR' not found (check CASESIGNAL_PHOTOS_ROOT / PHOTOS_DIR)"
echo "[$TS] syncing photos (incremental) from $PHOTOS_DIR ..."
gcloud storage rsync -r "$PHOTOS_DIR" "$BACKUP_BUCKET/photos" || fail "photos rsync failed"

# Heartbeat marker: lets an external check confirm backups are current without
# parsing logs. (Wire an alert on its staleness once observability lands.)
echo "$TS" | gcloud storage cp - "$BACKUP_BUCKET/last_success.txt" || fail "heartbeat write failed"

# Prune local scratch; cloud copies are retained by the bucket lifecycle.
# shellcheck disable=SC2012
ls -t "$WORKDIR"/casesignal_*.dump 2>/dev/null | tail -n +$((LOCAL_KEEP + 1)) | xargs -r rm -f

echo "BACKUP_OK: $TS -> $BACKUP_BUCKET (db + photos)"
