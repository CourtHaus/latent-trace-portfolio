# Latent Trace deployment runbook

This operator runbook covers the deployed Latent Trace architecture and an optional self-hosted topology. It assumes the current cold-case platform: FastAPI read/admin API, Next.js frontend, Postgres/PostGIS, ingestion worker, extraction worker, geocoding worker, and optional PostHog frontend telemetry.

## Deployment Shape

The production frontend origin is `https://latenttrace.org`. The deployed
architecture uses Vercel for the frontend, Google Cloud Run for the API, and
Supabase for Postgres, Auth, and Storage. Ingestion and enrichment run on an
operator machine, followed by an explicit data sync. Provider charges depend
on usage and account settings; this guide does not promise a free deployment.

Services:

- `postgres` — Postgres 16 + PostGIS 3.5.
- `casesignal-api` — FastAPI on `127.0.0.1:8000`, reverse-proxied by Caddy/nginx.
- `casesignal-ingestion-worker` — drains `etl.ingestion_job`.
- `casesignal-extraction-worker` — drains `cold_case.extraction_job`.
- `casesignal-geocoding-worker` — drains `cold_case.geocoding_job`.
- `frontend` — Next.js production server on `127.0.0.1:3000`.
- `caddy` or equivalent — TLS termination, HTTP to HTTPS redirect, HSTS.

The single-host service list also supports a self-hosted deployment. It is an alternative topology, not the current production configuration.

## Required Secrets and Env

Backend:

```bash
APP_ENV=production
DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/<db>
KEY_HMAC_SECRET=<32+ bytes of random hex or base64 material>
FRONTEND_ORIGINS=https://latenttrace.org
POSTGRES_USER=<db user>
POSTGRES_PASSWORD=<db password>
POSTGRES_DB=casesignal
```

Extraction backend:

```bash
# Local Ollama default. Keeps case narratives on owned infrastructure.
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=qwen3:14b

# Pinned model the extraction worker dispatches against the OpenAI-compatible
# endpoint above. Must be servable by that backend.
EXTRACTION_MODEL_ID=qwen3:14b
```

Use a hosted OpenAI-compatible endpoint only when the source/corpus has been approved for that provider. Do not send victim narratives to a SaaS LLM by accident.

Persistent data:

```bash
# REQUIRED in prod. Default is "data/photos" relative to the API/worker CWD,
# which means photos land inside the running git worktree. Point this at a
# stable directory OUTSIDE any worktree so `git worktree remove` or a
# redeploy cannot delete downloaded case photos. Honored by the ingestion
# adapter, the photo-serving endpoint, and the photo recovery tools
# (scripts/restore_missing_photos.py, scripts/backfill_photo_storage_path.py).
CASESIGNAL_PHOTOS_ROOT=/var/lib/casesignal/photos

# Filesystem root for admin ingestion uploads. Defaults to
# /tmp/casesignal_uploads; override for the same reason.
INGESTION_UPLOAD_ROOT=/var/lib/casesignal/uploads
```

Geocoding:

```bash
# Optional. If unset, Google is skipped and the ladder falls through to ZIP/county centroids.
GOOGLE_MAPS_API_KEY=
```

Frontend:

```bash
API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SITE_URL=https://latenttrace.org

# Optional telemetry. If key is unset, analytics is fully disabled.
NEXT_PUBLIC_POSTHOG_KEY=
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
```

For local tester previews, the frontend can proxy case-photo requests through
Next.js. A single public frontend URL is enough for browser testing; the
backend can stay on localhost behind it.

Never commit real environment files, database passwords, HMAC secrets, or privileged keys. Browser publishable keys are not authentication secrets, but configure them through deployment settings rather than hardcoding them.

## Split deployment (Vercel + Cloud Run + Supabase)

Use separate Preview and Production environments and credentials.

### Why split

- Vercel keeps frontend previews fast and globally cached.
- Cloud Run lets us run a small API-only container (`Dockerfile.api`) instead
  of booting the full Next.js + FastAPI stack in one container.
- Cloud Run runs the API on managed container infrastructure; set instance and billing limits for the account.

### Supabase prerequisites

1. Supabase Postgres is migrated to Alembic head.
2. Supabase Storage has a bucket named `case-photos`.
3. The bucket may be public or private:
   - Public bucket: the API can fetch photos without `SUPABASE_SERVICE_ROLE_KEY`.
   - Private bucket: set `SUPABASE_SERVICE_ROLE_KEY` on Cloud Run so the API can proxy photo bytes.
4. Upload local photos from the repo root. This operator-machine upload helper
   requires `SUPABASE_SERVICE_ROLE_KEY` in the local `.env` so it can write
   Storage objects and update `cold_case.case_photo.storage_path` rows through
   `DATABASE_URL`; this local upload requirement is separate from Cloud Run runtime
   photo reads.

   ```bash
   set -a
   source .env
   set +a

   SUPABASE_STORAGE_BUCKET=case-photos \
   python scripts/upload_photos_to_supabase_storage.py --dry-run

   SUPABASE_STORAGE_BUCKET=case-photos \
   python scripts/upload_photos_to_supabase_storage.py
   ```

### API setup (Cloud Run)

Set deployment variables for the intended account (replace placeholder values):

```bash
export PROJECT_ID='your-gcp-project-id'
export REGION=us-central1
export REPO=casesignal
export IMAGE=casesignal-api
export SERVICE=casesignal-api-preview
```

Enable required Google APIs and create (or reuse) an Artifact Registry repo:

```bash
gcloud auth login
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION" --description="CaseSignal preview containers"
```

Build and push the API image from `Dockerfile.api` via the repo-root
`cloudbuild.yaml`:

```bash
gcloud builds submit --config cloudbuild.yaml --region "$REGION" .
```

> **Why `--config`, not `--tag`/`-f`:** `gcloud builds submit` has no
> `-f`/`--file` flag, and `--tag` only builds a Dockerfile literally named
> `Dockerfile`. Since the API image comes from `Dockerfile.api`, `cloudbuild.yaml`
> runs an explicit `docker build -f Dockerfile.api`. The image path
> (`us-central1-docker.pkg.dev/$PROJECT_ID/casesignal/casesignal-api:preview`)
> is baked into that file — it matches `REGION=us-central1`, `REPO=casesignal`,
> `IMAGE=casesignal-api` above; update the file if those change.

Create `cloudrun-preview.env` from the repo root with **non-secret** runtime env
only. Secrets (`DATABASE_URL`, `KEY_HMAC_SECRET`) are injected from Secret Manager
via `--set-secrets`, not stored in this plaintext file — see SEC-A02/A03/A06 in
`docs/engineering-decisions.md`.

```bash
APP_ENV=production
FRONTEND_ORIGINS=https://latenttrace.org

# Trust this many reverse-proxy hops when reading X-Forwarded-For for per-IP
# rate limiting (SEC-B02). 0 = trust nothing (buckets collapse to one behind a
# proxy). Cloud Run *.run.app typically appends one hop, so 1 is the right start;
# verify against an actual request's X-Forwarded-For and bump if a custom LB is
# added in front. Setting this too high never lets a client spoof a bucket — the
# code falls back to the peer IP when the chain is shorter than the hop count.
RATE_LIMIT_TRUSTED_PROXY_HOPS=1

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<anon-or-publishable-key>
SUPABASE_STORAGE_BUCKET=case-photos
SUPABASE_STORAGE_PREFIX=

DATABASE_POOL_SIZE=2
DATABASE_MAX_OVERFLOW=1
DATABASE_POOL_TIMEOUT_SECONDS=30
```

Store the two runtime secrets in Secret Manager (one-time; re-run to rotate, see
the rotation section below):

```bash
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# DATABASE_URL — the live Supabase connection string (contains the DB password)
printf '%s' 'postgresql+psycopg2://...' | gcloud secrets create DATABASE_URL --data-file=- 2>/dev/null \
  || printf '%s' 'postgresql+psycopg2://...' | gcloud secrets versions add DATABASE_URL --data-file=-

# KEY_HMAC_SECRET — generate a PROD-ONLY value, distinct from local/.env (SEC-A02)
python -c 'import secrets; print(secrets.token_hex(32))' | gcloud secrets create KEY_HMAC_SECRET --data-file=- 2>/dev/null \
  || python -c 'import secrets; print(secrets.token_hex(32))' | gcloud secrets versions add KEY_HMAC_SECRET --data-file=-

for S in DATABASE_URL KEY_HMAC_SECRET; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

Deploy (non-secret env from the file, secrets from Secret Manager):

```bash
gcloud run deploy "$SERVICE" \
  --image "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE}:preview" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8000 \
  --cpu 1 \
  --memory 512Mi \
  --max-instances 2 \
  --min-instances 0 \
  --timeout 120 \
  --env-vars-file cloudrun-preview.env \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,KEY_HMAC_SECRET=KEY_HMAC_SECRET:latest"
```

**Redeploying after a code change (env unchanged).** There is no auto-deploy on
merge/push — rebuild by hand or the live frontend keeps hitting stale API code.
Rebuild the image (`gcloud builds submit --config cloudbuild.yaml --region "$REGION" .`),
then swap it in **without** `--env-vars-file` so the existing env/secrets are
preserved:

```bash
gcloud run deploy "$SERVICE" \
  --image "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE}:preview" \
  --region "$REGION"
```

Backward-compatible image swaps (added fields / new optional params) are safe to
ship this way. Verify with `curl`-and-time against the service URL afterwards.

**Cold-start vs cost trade-off.** `--min-instances=0` allows the service to scale to zero
when idle but means almost every uncached request hits a cold start (a small
Python container typically takes 5–15s to boot). The frontend's `apiFetch`
default timeout is 30s to absorb this. If preview traffic grows enough that
cold-start latency hurts UX, switch to `--min-instances=1` (always-on billing,
no cold starts) and drop the `apiFetch` timeout to ~8–10s.

Optional private-bucket setup (recommended via Secret Manager):

```bash
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
echo -n "<service-role-key>" | gcloud secrets create SUPABASE_SERVICE_ROLE_KEY --data-file=-
gcloud secrets add-iam-policy-binding SUPABASE_SERVICE_ROLE_KEY \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud run services update "$SERVICE" \
  --region "$REGION" \
  --update-secrets SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest
```

Leave `SUPABASE_SERVICE_ROLE_KEY` unset for public Storage buckets. Never put
it in `NEXT_PUBLIC_` variables.

Read the API base URL after deploy:

```bash
API_BASE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo "$API_BASE_URL"
```

### Frontend setup (Vercel)

Create/import a Vercel project for the `frontend/` directory of this repo.

Required Vercel environment variables:

```bash
API_BASE_URL=https://<your-cloud-run-api-domain>
NEXT_PUBLIC_SITE_URL=https://latenttrace.org
NEXT_PUBLIC_CARTO_BASEMAP_API_KEY=<carto-basemaps-key>

NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-or-publishable-key>
```

Optional telemetry variables:

```bash
NEXT_PUBLIC_POSTHOG_KEY=
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
```

Set `API_BASE_URL` for both Preview and Production environments in Vercel.
Case detail photos are served via Next.js rewrites to this API origin.

#### CARTO map backgrounds

Both the main map and case-detail maps require a CARTO Basemaps key to remove
the provider's "API key required" watermark. Request one at
[CARTO Basemaps](https://www.carto.com/basemaps/apikey/), then set
`NEXT_PUBLIC_CARTO_BASEMAP_API_KEY` in `frontend/.env.local` for development
and in Vercel's Preview and Production environments. Restart the dev server
locally; rebuild/redeploy on Vercel because Next.js embeds `NEXT_PUBLIC_`
variables into the browser bundle at build time.

Use a Basemaps key, which is intentionally sent in browser tile URLs. Configure
its origin restrictions in CARTO's dashboard for the domains where the maps
run (including localhost or preview domains as needed). Keep CARTO and
OpenStreetMap attribution visible on both maps. See CARTO's key page for
current free-tier limits and pricing.

After deploying, open `/cold-cases/map` and a geocoded case detail. Confirm
tile requests contain `?key=...` and the backgrounds have no watermark;
hard-refresh if old tiles remain cached.

### Syncing local Postgres → Supabase

After each ingest, push the new data + any pending migrations to Supabase with a single script. Local Postgres is the source of truth; Supabase's user-data is fully replaced on every sync.

**One-time setup (first time only):**

1. Confirm the Cloud Run `DATABASE_URL` secret references the intended Supabase database. Do not put that secret in `cloudrun-preview.env`.
2. Add `SUPABASE_DATABASE_URL=<same value>` to `.env` (a separate variable from
   the local `DATABASE_URL`, to prevent accidental aim-at-prod).
3. `scripts/sync_to_supabase.sh --dry-run` — read output, confirm the row-count
   replacement preview matches expectations.

**Recurring procedure:**

```bash
set -a
source .env
set +a

scripts/sync_to_supabase.sh                 # data + schema migrations
scripts/sync_to_supabase.sh --with-photos   # also chain the photo upload
scripts/sync_to_supabase.sh --dry-run       # see what would change, no writes
```

The script runs 5 phases (pre-flight, alembic upgrade head, pg_dump + TRUNCATE + restore inside one transaction, row-count verification, optional photo upload). Hard exit codes per phase: 1 pre-flight, 2 schema, 3 data, 4 verify. Photos step failure is logged but does not change the exit code; re-run the photo upload script standalone.

`scripts/sync_to_supabase.sh --help` for the full flag list.

**Schema in scope.** The sync replaces `cold_case.*`, `etl.*`, `raw_cold_case.*`, `audit.*`, and `app_auth.*` on Supabase. Supabase-managed schemas (`auth.*`, `storage.*`, etc.) are never touched. The `app_auth.api_keys` admin allowlist is now local-managed — add operators to local DB first, then sync to push them up.

**Backups.** The sync script takes no pre-sync backup. Before replacing remote data, create and verify a private target backup and confirm the account's actual recovery options. Do not assume provider backups or point-in-time recovery are enabled. See [backup and restore](../RESTORE.md).

**Integration test.** `tests/integration/test_sync_to_supabase.sh` runs the full script against two ephemeral local Postgres containers. Run it before pushing to production for the first time, and after every change to the sync script or any migration that touches the dumped schemas.

See `docs/engineering-decisions.md` for the design rationale.

### Supabase Auth for `/admin`

1. In Supabase Authentication settings, set the Site URL to the Vercel origin,
   for example `https://latenttrace.org`.
2. Add an allowed redirect URL for
   `https://latenttrace.org/auth/callback`.
3. Create the single admin user in Supabase Authentication. The app sends magic
   links with `shouldCreateUser=false`, so public visitors cannot self-create
   operator accounts through `/admin/login`.
4. Run the allowlist script from an operator machine with `DATABASE_URL` pointed
   at the local operator database, then sync the allowlist to Supabase:

   ```bash
   set -a
   source .env
   set +a
   PYTHONPATH=src:. python scripts/allowlist_supabase_admin.py --email you@example.com
   ```

### Preview smoke test

After Vercel and Cloud Run finish deploying:

```bash
curl --fail https://<your-cloud-run-api-domain>/healthz
```

```bash
PYTHONPATH=src:. \
python scripts/smoke_preview.py \
  --base-url https://latenttrace.org
```

The smoke check requests `/privacy`, `/`, `/cold-cases`, `/cold-cases/map`, the
first case detail link found on the list page, and the first case photo found
on that detail page.

## Secret rotation

Historical audit observations do not establish the current status of deployed
credentials. Recover and rotate credentials through their provider or secret
manager; never copy real values into documentation or command history.
See [environment recovery](environment-recovery.md).

Use different local and production HMAC secrets. Rotation invalidates existing
API-key fingerprints, so revoke and reissue API keys. Offboarding must also
disable the separate Supabase operator allowlist entry and sessions. Rotate
database credentials and service-role keys at their providers, update secret
references, redeploy affected services, and verify health and authentication.

## First Deploy

1. Confirm CI is green on `main`.
2. Provision the VPS, firewall it to `22`, `80`, and `443`, and keep Postgres bound to localhost or an internal network.
3. Create production env files out of band.
4. Install the backend package and frontend dependencies.
5. Run database migrations:

   ```bash
   DATABASE_URL=... alembic upgrade head
   ```

6. Start the API:

   ```bash
   APP_ENV=production DATABASE_URL=... KEY_HMAC_SECRET=... casesignal-api
   ```

7. Start workers:

   ```bash
   casesignal-ingestion-worker
   casesignal-extraction-worker
   casesignal-geocoding-worker
   ```

8. Build and start the frontend:

   ```bash
   cd frontend
   API_BASE_URL=http://127.0.0.1:8000 pnpm install --frozen-lockfile
   API_BASE_URL=http://127.0.0.1:8000 pnpm build
   API_BASE_URL=http://127.0.0.1:8000 pnpm start
   ```

9. Put Caddy/nginx in front of frontend and API. Route public browser traffic to the frontend; keep direct API/admin access controlled.

## Local Tester Preview

For a product-test preview from a dev machine:

1. Use an empty migrated development database or a separately approved test corpus; do not restore production history for a preview.
2. Start the backend on `127.0.0.1:8000`.
3. Start the frontend with `API_BASE_URL=http://127.0.0.1:8000`.
4. Expose only the frontend origin through a tunnel such as ngrok or Cloudflare Tunnel.
   For ngrok dev previews, start Next with the public host allowed:

   ```bash
   API_BASE_URL=http://127.0.0.1:8000 \
   NEXT_PUBLIC_SITE_URL=https://<ngrok-host> \
   ALLOWED_DEV_ORIGINS=<ngrok-host> \
   pnpm dev
   ```

   If neither client is installed, use the no-install SSH fallback:

   ```bash
   ssh -o ServerAliveInterval=30 -R 80:localhost:3000 nokey@localhost.run
   ```

Because case-detail photos are proxied through Next.js, testers only need the
public frontend URL.

## Smoke Checks

Backend:

```bash
curl --fail https://<api-origin>/healthz
curl --fail https://<api-origin>/api/v1/cold-cases/filter-options
```

Frontend:

- Open `/`.
- Open `/cold-cases`.
- Open `/cold-cases/map`.
- Open a case detail page and verify source-reveal highlighting.
- Open `/methodology`.
- Open `/privacy`, click the opt-out button, and confirm the opted-out state appears.

Telemetry:

- In PostHog project settings, enable **Discard client IP data** and verify it
  in the deployed project. The SDK's deprecated `ip` setting does not control
  server-side IP retention; client event redaction cannot hide a network address.
  See [PostHog's IP handling guidance](https://posthog.com/tutorials/web-redact-properties#hiding-customer-ip-address).

- With `NEXT_PUBLIC_POSTHOG_KEY` unset, confirm no PostHog network calls are emitted.
- With the key set in staging, confirm only the seven documented events appear and no filter values, querystrings, raw phrases, offsets, names, or addresses are captured.

Workers:

```sql
SELECT status, count(*) FROM etl.ingestion_job GROUP BY status;
SELECT status, count(*) FROM cold_case.extraction_job GROUP BY status;
SELECT status, count(*) FROM cold_case.geocoding_job GROUP BY status;
```

Expected steady state: no long-running `running` jobs older than the configured crash-recovery window; failed jobs are explainable and have `error_detail` / `notes`.

## Backups and restore drills

Use the [backup and restore guide](../RESTORE.md). Set an explicit private
backup bucket and test recovery into a fresh database. `pg_dump` requires a
libpq URL; the backup helper normalizes the `postgresql+psycopg2` driver prefix.
Keep dumps and photo collections out of Git and public build artifacts.

## Rollback

Application rollback:

1. Stop frontend/API/workers.
2. Check out the previous known-good commit.
3. Reinstall dependencies if lockfiles changed.
4. Restart API, workers, and frontend.
5. Run smoke checks.

Database rollback:

- Prefer forward fixes when possible.
- If a migration corrupts production data, stop writers first, restore the last verified backup, then redeploy the known-good application commit.

## Release Checklist

- CI green on the release commit.
- `docs/security-backlog.md` has no stale deploy-blocking findings.
- Production env file exists outside git.
- `KEY_HMAC_SECRET` generated and stored in the secret manager/password vault.
- Database backup job installed.
- Restore drill completed.
- API health and frontend smoke checks completed.
- `/privacy` accurately matches telemetry configuration.
- PostHog project uses the intended US/EU region and only the public project key is exposed to the browser.
- Admin API key issued with `scripts/create_api_key.py` and stored securely.
