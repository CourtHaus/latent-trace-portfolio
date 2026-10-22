# Data, provenance, and privacy

Latent Trace aggregates official public case records for research. Public
availability is not a blanket license to redistribute text, photographs, or
personal information. This guide describes data boundaries and review duties;
it does not grant rights in third-party material.

## Source and interpretation rules

Record the publishing agency, source URL, retrieval context, and transformation
when adding an adapter. Respect source terms and access restrictions; do not
capture authenticated pages, bypass access controls, or commit session cookies.
Capture only the material needed for a parser test. Prefer synthetic fixtures
for failures, unusual demographics, and security regressions.

Preserve distinctions between publisher facts, model-extracted fields, and
geographic approximations. Race is not extracted by the narrative model.
Do not infer demographics from names or photographs. Correlation scores express
shared characteristics under the implemented scoring rule, not probabilities
of a shared offender. Coverage and missingness vary by source.

## External data flows

| Component | Data that may leave the operator machine or browser |
| --- | --- |
| Source ingestion | Requests to agency hosts, including URLs and the scraper contact header |
| Narrative extraction | Narrative text sent to the configured OpenAI-compatible endpoint; default is local Ollama |
| Source Scout / Adapter Drafter | Captured source evidence and code supplied to the configured hosted assistant workflow |
| Geocoding | Address queries to Census and, when enabled, Google; ZIP/county lookup is local |
| Production serving | Selected database schemas synced to Supabase; API on Cloud Run and frontend on Vercel |
| Map backgrounds | Browser tile requests to CARTO, revealing network and requested map-area information |
| Operator login | Authentication exchanges with Supabase |
| Telemetry | PostHog events and Sentry diagnostics when enabled; Vercel Speed Insights performance collection |

A local extraction default is not a promise that all application data stays
on local hardware. Review provider settings and source permissions before
running a hosted workflow. Do not supply private tips, correspondence, or
credentials to model prompts.

## Repository boundaries

Keep database dumps, bulk source exports, photo collections, `.env` files,
agent transcripts, and runtime registries out of Git. Runtime directories
under `data/raw`, `data/photos`, `data/scout`, and `data/drafts` are ignored.
Synthetic parser examples are documented under [tests/fixtures](../tests/fixtures/README.md);
Census-derived reference tables have [separate provenance](../data/static/README.md).
Neither category is relicensed by the project's reserved-rights notice.

Deleting a tracked file does not remove it from earlier commits. Before a
visibility change, review reachable history and GitHub-hosted issues, PRs,
attachments, Actions logs, and artifacts. The
[snapshot review](snapshot-review.md) records what was excluded from this
repository. The private repository retains its original history and evidence.

## Corrections and removal requests

Contact [courtney@latenttrace.org](mailto:courtney@latenttrace.org) with the
page URL and the minimum explanation needed. Do not place personal case
information in a public issue. Verify corrections against the source, preserve
an internal explanation, and consider cached pages, photos, exports, and
backups when carrying out a removal. The public
[privacy page](https://latenttrace.org/privacy) describes visitor-facing handling.
