# Corpus backup and restore

Back up the database and photo collection to private storage outside Git.
A database dump can contain source records, model output, authentication
metadata, and operational history. It is not a public development seed.

## Back up

Set `DATABASE_URL`, `BACKUP_BUCKET` (your private `gs://` destination), and
`CASESIGNAL_PHOTOS_ROOT` in a trusted local environment. Use PostgreSQL client
tools compatible with the database and authenticate `gcloud` to the intended
account. Then run:

```bash
scripts/backup_corpus.sh
```

The script writes a custom-format database dump, checks its archive directory
with `pg_restore --list`, uploads it, synchronizes photos, and writes a
`last_success.txt` heartbeat. A directory check does not prove a complete
restore works; perform the drill below. Local dump permissions are restricted
by `umask 077`; configure cloud IAM, retention, and versioning separately.

Set `BACKUP_WORKDIR` for local scratch storage and `PHOTOS_DIR` only when
intentionally overriding the application photo root. The script retains seven
local dump copies. Cloud lifecycle rules are operator-managed, not established
by this script. Confirm them in the actual bucket before relying on retention.

Schedule backups with your host's scheduler and monitor both failed runs and
stale heartbeats. Keep credentials outside scheduler command lines and logs.

## Restore into a fresh local database

Download a specifically selected backup to private local storage. Supply the
PostgreSQL connection settings through your local environment or password
file, then choose a new database name:

```bash
export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=casesignal
export PGDATABASE=casesignal_restore_review
tools/restore_local_seed.sh /private/path/selected-backup.dump
```

Despite its legacy filename, this helper accepts an operator-provided backup,
not a Git revision. It requires a local host and a fresh `casesignal_restore_`
database name. It refuses to replace an existing database. Restore failures
may leave the new empty database for inspection; no existing corpus is truncated.

Verify schema migrations, per-source counts, extraction results, publication
status, and representative API responses. Restore photos to a separate scratch
directory and point the scratch application at it. Do not sync restored data
to production as part of a drill.

## Production recovery

Choose the recovery point and target explicitly. Stop writers, preserve a
backup of the current target, and review authentication records included in
the dump. Test the selected backup in isolation first. Follow the
[deployment runbook](deploy/runbook.md) for migration compatibility, application
rollback, and post-recovery smoke checks. Restore database and photo versions
that correspond to the same recovery point where possible.
