#!/usr/bin/env bash
# Restore an operator-supplied custom-format backup into a fresh local database.
# Never retrieves a production corpus from Git history or truncates a database.
set -euo pipefail
umask 077

if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: PGDATABASE=casesignal_restore_NAME tools/restore_local_seed.sh /path/to/backup.dump"
  echo "Requires a fresh local database name, PostgreSQL client tools, and configured PG credentials."
  exit 0
fi
[[ $# == 1 && -f "$1" ]] || { echo "Supply an existing custom-format backup file; see --help." >&2; exit 1; }
export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5433}"
export PGUSER="${PGUSER:-casesignal}"
[[ "$PGHOST" == 127.0.0.1 || "$PGHOST" == localhost || "$PGHOST" == ::1 ]] || {
  echo "Restore helper only accepts a local database host." >&2; exit 1;
}
[[ "${PGDATABASE:-}" =~ ^casesignal_restore_[a-zA-Z0-9_]+$ ]] || {
  echo "Set PGDATABASE to a fresh name beginning casesignal_restore_." >&2; exit 1;
}
export PGDATABASE
pg_restore --list "$1" >/dev/null
# createdb fails if the destination exists. No existing database is replaced.
createdb -- "$PGDATABASE"
pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
  --dbname "$PGDATABASE" "$1"
printf 'Restored into %s. Verify counts, migrations, and application behavior before use.\n' "$PGDATABASE"
