# Local development

This guide sets up an authorized development checkout with an empty database.
The project reads backend settings from the process environment; it does not
automatically load `.env`. The frontend loads `frontend/.env.local` through Next.js.

## Prerequisites

Use Python 3.11 or 3.12 (CI covers both), `uv`, Docker Compose, PostgreSQL client
tools, Node.js 22+, and pnpm 10.33.2. PostgreSQL client tools include `psql`,
`createdb`, `pg_dump`, and `pg_restore`. Go is needed for the first pre-commit
Gitleaks installation. Ollama, Supabase, and hosted AI accounts are optional
and are not required for the ordinary test suite.

The [rights notice](../LICENSE) applies to the source. These instructions do
not grant a separate reuse license.

## Configure the backend

From the repository root, install the locked dependencies and create a local
configuration file. Do not overwrite an existing `.env`:

```bash
uv sync --frozen --extra dev
test -e .env || cp .env.example .env
```

Edit `.env`: replace `POSTGRES_PASSWORD` and set `KEY_HMAC_SECRET` to separate
random values. Generate each value locally with
`python3 -c 'import secrets; print(secrets.token_hex(32))'`. Hex values work in
the example connection URL without additional URL encoding. Use `APP_ENV=dev`
locally; deployed environments must use `production` and independent secrets.

Load your trusted local file, start the database, and apply migrations:

```bash
set -a
source .env
set +a
docker compose up -d postgres
uv run --extra dev alembic upgrade head
uv run --extra dev pre-commit install
```

Compose binds Postgres to `127.0.0.1:5433`. Port `5432` is internal to the
container. If migrations run before Postgres is ready, wait for
`docker compose exec postgres pg_isready -U casesignal` and retry. Changing a
password in `.env` does not change an existing database volume's password.

Start the API in the same environment:

```bash
uv run casesignal-api
```

Check [health](http://127.0.0.1:8000/healthz) and
[OpenAPI documentation](http://127.0.0.1:8000/docs). Public lists are empty
until a source has been ingested and published. The production corpus is not
a development prerequisite and is not distributed as a seed.

## Configure the frontend

In another terminal, from `frontend/`:

```bash
pnpm install --frozen-lockfile
test -e .env.local || cp .env.local.example .env.local
pnpm dev
```

Visit [localhost:3000](http://localhost:3000). Keep `API_BASE_URL` pointed at
your local API. A CARTO Basemaps key is needed for watermark-free maps; it is
browser-visible and belongs in `NEXT_PUBLIC_CARTO_BASEMAP_API_KEY`. Supabase
Auth settings are needed only for operator login. See the
[frontend guide](../frontend/README.md).

## Isolate tests from operator data

The test harness redirects database access to `TEST_DATABASE_URL` and requires
a test sentinel. Integration fixtures mutate their target database. Never
stamp that sentinel on an operator or production database.

After loading `.env`, create the dedicated local test database:

```bash
export TEST_DB_PASSWORD="$POSTGRES_PASSWORD"
tools/create_test_db.sh
export TEST_DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5433/casesignal_test"
uv run --extra dev pytest -m 'not extractor_validation' --tb=short
```

For custom Compose usernames, also set `TEST_DB_USER`. The test helper defaults
to `casesignal` and the database `casesignal_test`. Unit tests also load the
shared database guard, so create the test database before selecting a unit file.
The original recorded-model accuracy gate and agency capture tests are not
distributed in this snapshot; see [fixture scope](../tests/fixtures/README.md).
The included loader test uses a temporary synthetic label file.

Run static checks from the root:

```bash
uv run --extra dev ruff check src tests scripts
uv run --extra dev mypy src tests
uv run --extra dev pre-commit run --all-files
python3 scripts/check_repository_docs.py
```

Run frontend checks from `frontend/`, with the local API running for the build:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Regenerate API types with `pnpm types:api` after an OpenAPI change. Review the
generated diff. CI also builds against an empty migrated database, so pages
must handle missing records.

## Optional operator workflows

The installed command names retain the `casesignal-` prefix:

| Command | Purpose |
| --- | --- |
| `casesignal-etl` / `casesignal-etl-inspect` | Ingest or inspect a configured source |
| `casesignal-ingestion-worker` | Consume ingestion jobs |
| `casesignal-extract-cold-cases` / `casesignal-extraction-worker` | Run narrative extraction |
| `casesignal-promote-victim-demographics` | Promote eligible extraction results |
| `casesignal-geocoding-worker` | Consume geocoding jobs |
| `casesignal-source-scout` | Discover and prepare candidate sources |
| `casesignal-adapter-draft` | Capture, draft, verify, and finish an adapter |

Use `--help` on command-line interfaces and read their runbooks before running
operations. Ingestion fetches external data; extraction and geocoding may
make external calls depending on configuration. The drafter's grading sandbox
requires Linux with Landlock ABI 3 or newer and libseccomp; see its
[runbook](runbooks/adapter-drafter.md) for provider and isolation requirements.

The recorded-model evaluation tool expects privately supplied labels and responses
under ignored `data/validation/`. Those datasets are not bundled or synthesized
into an accuracy benchmark.

For local narrative extraction, install Ollama, run `ollama pull qwen3:14b`,
and keep `OPENAI_BASE_URL=http://localhost:11434/v1`. Hosted model endpoints
send supplied narratives to the configured provider. Source Scout and Adapter
Drafter are separate workflows and may use hosted Claude tooling.
