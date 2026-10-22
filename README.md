<img src="branding/assets/latent_logo.svg" alt="Latent Trace" width="390" />

# Latent Trace

A research platform for exploring cold-case records from official public
sources. Latent Trace brings together source ingestion, narrative extraction,
geographic search, and comparisons between cases in a searchable web interface.

**[Visit latenttrace.org](https://latenttrace.org)** ·
[Documentation](docs/README.md) · [Architecture](docs/architecture.md) ·
[Report a problem](SUPPORT.md)

**Portfolio source snapshot.** The live application is developed and deployed
from a separate private repository. This copy includes application code and
synthetic tests; private history and source captures are excluded. Read the
[snapshot review](docs/snapshot-review.md) and
[engineering decisions](docs/engineering-decisions.md).

Built and maintained by **Courtney Hammond** —
[courtney@latenttrace.org](mailto:courtney@latenttrace.org).

## What it does

- Ingests heterogeneous agency publications through source-specific adapters,
  retaining provenance and separating raw records from published datasets.
- Offers list, map, and case-detail views with shared filters, source links,
  geocoding precision, and source-text highlights for extracted fields.
- Uses structured narrative extraction with a local Ollama default. Hosted
  model endpoints are configurable; geocoding and optional source-drafting
  tools have separate external data flows.
- Ranks cases with shared characteristics using rarity-weighted scoring and
  geographic and temporal filters. Results support human review and do not
  establish a connection between cases or identify an offender.
- Separates public reads from authenticated administration and asynchronous
  ingestion, extraction, and geocoding workers.

The project is pre-1.0 and independently maintained. Coverage reflects the
sources ingested, not all unsolved cases. Missing fields, uncertain dates,
approximate map locations, and source changes affect interpretation. Read the
[methodology](https://latenttrace.org/methodology) and
[data-handling guide](docs/data-and-privacy.md).

## Engineering overview

| Layer | Implementation |
| --- | --- |
| API and pipelines | Python 3.11+, FastAPI, SQLAlchemy, Alembic |
| Storage and spatial queries | PostgreSQL 16 with PostGIS 3.5 |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, Leaflet |
| Local extraction default | Ollama with `qwen3:14b` |
| Deployment | Vercel frontend, Cloud Run API, Supabase Postgres/Auth/Storage |
| Verification | pytest, Ruff, mypy, Vitest, ESLint, production build, dependency and secret scans |

`casesignal` remains the Python package, CLI prefix, and database naming
convention for compatibility with the project's earlier name.

## Repository map

| Path | Purpose |
| --- | --- |
| [src/casesignal/etl](src/casesignal/etl/) | Source catalog, adapters, ingestion pipeline |
| [src/casesignal/api](src/casesignal/api/) | Public API and authenticated administration |
| [src/casesignal/extraction](src/casesignal/extraction/) | Narrative extraction and provenance |
| [src/casesignal/correlation](src/casesignal/correlation/) | Candidate retrieval and scoring |
| [src/casesignal/worker](src/casesignal/worker/) | Queue consumers |
| [src/casesignal/scout](src/casesignal/scout/) / [drafter](src/casesignal/drafter/) | Operator tools for discovering and drafting sources |
| [frontend](frontend/) | Web application |
| [migrations](migrations/) / [tests](tests/) | Schema changes and verification |
| [scripts](scripts/) / [tools](tools/) | Python operations scripts / shell, SQL, and browser tools |
| [docs](docs/) | Current guides, runbooks, and engineering decisions |

## Development

The [development guide](docs/development.md) covers an authorized local setup,
configuration, database isolation, tests, and common commands. It uses the
committed `uv.lock` and `frontend/pnpm-lock.yaml`. A fresh checkout starts with
an empty database; a production corpus or historical database dump is not
required to run the tests.

For deployment, use the [operator runbook](docs/deploy/runbook.md). For source
tooling, start with [Source Scout](docs/runbooks/source-scout.md) and
[Adapter Drafter](docs/runbooks/adapter-drafter.md). Original development plans
and operational evidence remain in the private repository.

## Rights and contact

Copyright © 2026 Courtney Hammond. **All rights reserved.** This project is
not open source and grants no general permission to reuse or redistribute
its original code. See [LICENSE](LICENSE) for the notice and platform-terms
exception. Third-party data and dependencies retain their own rights.

For permission requests, feedback, or case corrections, email
[courtney@latenttrace.org](mailto:courtney@latenttrace.org). See
[CONTRIBUTING.md](CONTRIBUTING.md), [SUPPORT.md](SUPPORT.md), and
[SECURITY.md](SECURITY.md) for the appropriate reporting channel.
