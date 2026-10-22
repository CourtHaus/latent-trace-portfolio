# Latent Trace behavioral requirements

## Purpose

Behavioral reference for the Latent Trace cold-case platform, reviewed against the implementation on 2026-10-22. Each functional requirement (FR-NNN) describes one testable behavior the system shall support, with a traceability anchor to the PR, migration, or source file that delivers it. Use this doc as the "is the platform doing what it's supposed to?" reference during code review and operational verification.

## Scope

Covers the cold-case data platform as it exists after the Phase 0 pivot (PR #45, 2026-05-08). The pre-pivot platform — NIBRS analytics, jurisdiction comparison, generative LLM briefings — was demolished in Phase 0; that surface is documented in `CHANGELOG.md` under `## 0.1.0 — Phase 0` and is not in scope here.

Current code and tests are authoritative when a dated plan disagrees with this reference. Rarity-weighted correlation and operator source tooling are implemented; deferred proposals remain in the design archive. Coverage changes with the deployed source catalog.

## Principles

1. **Source integrity.** Cases are sourced only from official county or state law-enforcement publications. News aggregators, state-derived secondhand registries, and Doe Network–style compilations are explicitly excluded.
2. **Investigator framing.** Outputs are leads for analyst review, never suspect identification. Correlation, geocoding, and extraction all surface relationships and inferences; they never assert culpability.
3. **Demographic discipline.** Race comes from structured source data and is never extracted by the LLM. Narrative extraction may supply age and gender with provenance. Photos and names are never acceptable inference sources.
4. **Extraction transparency.** Every extracted field is an overlay on the source narrative, not a replacement. Each carries a character-offset pair into the narrative so users can verify provenance; reveal-source affordances are required at every render site.

---

## 1. Data Ingestion

**FR-001 — Adapter hooks and shared normalization**

Each source ingestion runs the adapter pipeline: `prepare_input` → `register_source` → `load_raw` → `transform` → shared `normalize_dataset_stage` → `publish`. There are five adapter hooks and six runner stages. Stages run sequentially; failure at any stage marks the `ingestion_run` failed and prevents downstream stages from executing.

Anchor: `src/casesignal/etl/adapters/base.py`

**FR-002 — Drift gate against baseline count**

Each adapter compares its live source row count against `source.metadata.baseline_count` from the YAML. Divergence ≥ 5% emits a warning; divergence ≥ 20% aborts the run with a `RuntimeError`. Re-runs after baseline refresh require either updating the YAML or accepting drift.

Anchor: `src/casesignal/etl/adapters/cold_case_oh_ag/scrape_search.py:drift_check` (reused by OH, NH, and future symmetric-drift adapters)

**FR-003 — Provenance on canonical fields**

Every canonical field that can be filled from multiple sources carries a `*_source` companion column. Permitted values: `'source'` (direct from publisher), `'tier2'` (LLM-extracted), `'source-mo'` (synthetic structured row at `prompt_tier=1, model_id='source'`). Fields without a `*_source` value are unprovenanced and surface as such on the detail page.

Anchor: Migration 0007

**FR-004 — Source county FIPS**

Each ingested case carries `cases.source_county_fips` as a 5-digit string where the source's geographic resolution permits. Adapter-local `county_fips.py` modules implement the town/county → FIPS lookup. Unmappable cases hold NULL and are flagged in adapter logs.

Anchor: Migration 0002 + per-state `county_fips.py`

**FR-005 — Idempotent re-ingestion**

Re-ingesting the same source content produces no duplicate cases. Adapters compute `source_hash` over the canonicalized source-row list and reuse the existing `dataset_version_id` when the hash matches. Per-case insertion is gated on `(dataset_version_id, source_case_id)` uniqueness.

Anchor: `register.py` get-or-create on `(source_system_id, source_hash)`

**FR-006 — Photo storage + serving**

Each adapter writes victim photos under `data/photos/<adapter_name>/<subdir>/<filename>` — most adapters key the subdir on `source_case_id`, but the convention is not enforced (OH and CO use a source-side id). SHA256, content-type, alt-text, source URL, and the file's path relative to the photos root are recorded in `cold_case.case_photo`; the `storage_path` column is the authoritative location. `GET /api/v1/cold-cases/{case_id}/photos/{filename}` serves `storage_path` directly (falling back to catalog-derived `<adapter>/<source_case_id>/` resolution when it is NULL), so the on-disk subdir convention need not be uniform across adapters. Each adapter's transform writes `storage_path` at ingest time; `scripts/backfill_photo_storage_path.py` re-derives it from the photos directory by content hash and is kept as a recovery tool for photo files restored out-of-band. Placeholder silhouettes (`female.jpg`, `male.jpg`, `default_social_card.png`, `unidentified-*`) are filtered at ingest time and not stored — surfacing them would falsely imply victim photos.

Anchor: Migration 0010 (`case_photo.storage_path`) + `src/casesignal/api/routes/cold_cases.py:get_cold_case_photo` + per-state `raw_load.py` + `cold_case_nh_doj/scrape_detail.is_placeholder_photo`

## 2. Structured Extraction

**FR-007 — Tier-1 enum fields**

Tier-1 extraction produces `weapon` and `location_type` from `cases.about_text` against fixed enums:
- `weapon` ∈ {firearm, knife, blunt, personal, asphyxiation, fire, other, unknown}
- `location_type` ∈ {residence, commercial, vehicle, public_outdoor, other, unknown}

Out-of-enum values from the LLM coerce to `unknown` with `*_low_confidence=TRUE`.

Anchor: `src/casesignal/extraction/cold_case/extract_case.py`

**FR-008 — Tier-2 narrative fields**

Tier-2 extraction produces incident_date (ISO 8601), address (free-text), victim_age (integer 0-130), victim_gender ('M' | 'F' | NULL) from the narrative. Tier-2 runs only on sources whose taxonomy doesn't already publish these fields structured.

Anchor: `src/casesignal/extraction/cold_case/tier2_extract_case.py`

**FR-009 — Source-span requirement**

Every extracted field carries a `*_source_start` / `*_source_end` character-offset pair pointing into `about_text`, OR is marked `*_low_confidence=TRUE`. Spans use character offsets, not byte positions, so that the frontend `NarrativeWithHighlights` component can render exact-character highlights.

Anchor: `src/casesignal/extraction/cold_case/offsets.py:resolve_offsets`

**FR-010 — Synthetic source-MO rows**

Sources where weapon + location_type + demographics are all structured at the publisher (Wyoming DCI being the canonical example) skip the LLM entirely. The adapter writes a synthetic `case_extractions` row at `prompt_tier=1, model_id='source', prompt_hash='source-v1', extractor_version='SOURCE'` with the structured values. Source-MO rows have NULL source-spans; the frontend hides the reveal-source link when spans are NULL.

Anchor: `src/casesignal/etl/adapters/cold_case_wy_dci/transform.py`

**FR-011 — Race-inference discipline**

Race is not part of the Tier-2 model output. Preserve source-published structured race values and their provenance; never infer race from narrative text, photographs, or names. Gender and age extraction follow the Tier-2 prompt and span-validation rules.

Anchor: `src/casesignal/extraction/cold_case/tier2_extract_case.py` and the current prompts under `src/casesignal/extraction/cold_case/prompts/`

**FR-012 — Defensive scalar coercion at LLM boundary**

LLM tool-call arguments are coerced through a scalar-only filter (`_coerce_scalar`) before reaching the typed field builders. Nested dicts, lists, and booleans become NULL rather than crashing or being stored as garbage. Required after Qwen was observed returning `{"value": "M"}` for victim_gender; the unprotected path crashed mid-flight during NH ingest.

Anchor: `src/casesignal/extraction/cold_case/tier2_extract_case.py:_coerce_scalar` (PR #81)

**FR-013 — Worker exception propagation**

The extraction worker's per-case extractor function (`extract_case` / `extract_case_tier2`) propagates LLM-API exceptions to the queue handler, which marks the job `status='failed'` and writes the exception class + message to `notes`. Silent-success on LLM error is explicitly forbidden — the OH AG ingest in PR #73 lost 2,796 cases to this bug before PR #78 fixed it.

Anchor: PR #78

## 3. Geocoding

**FR-014 — Five-tier ladder**

Geocoding attempts run in order: Census street geocoder → Google Maps geocoder → ZIP centroid → county centroid → failed. Each tier is invoked only if the prior tier produces no usable result. Census is free; Google is env-gated by `GOOGLE_MAPS_API_KEY` and skipped when unset. ZIP and county centroids come from committed static data under `data/static/`.

Anchor: `src/casesignal/geocoding/service.py`

**FR-015 — Precision enum**

Each geocoded case carries `cases.geocode_precision` ∈ {'street', 'landmark', 'zip', 'county', 'failed'}. Precision drives map pin styling (FR-031) and is filterable on list/map endpoints (FR-021/022). `'failed'` cases have NULL `latitude`/`longitude`.

Anchor: Migration 0005

**FR-016 — Closed-loop Tier-2 → geocoding**

When Tier-2 successfully extracts a non-null `address_text` AND the case's current `geocode_precision` is one of {NULL, 'failed', 'county'}, the persistence layer enqueues a new `geocoding_job` with the extracted address. The geocoding worker runs the upgraded address through the 5-tier ladder; success replaces the prior coordinates and precision. Cases already at 'street'/'landmark'/'zip' are skipped — Tier-2's extracted address can't improve them.

Anchor: `src/casesignal/extraction/cold_case/persistence.py:enqueue_geocoding_job_from_tier2`

**FR-017 — Bare-state-name guard**

When the input `address_text` is a bare US state name (e.g., "Utah", "New Hampshire"), the geocoding service skips the Census and Google tiers and falls through to state-centroid fallback. Without this guard, Google's geocoder happily plots "Utah" at 39.32°N 111.09°W with `street` precision — a false high-confidence pin in the middle of the state.

Anchor: PR #69

## 4. Correlation

**FR-018 — Hard spatial + temporal filter**

Cold-case ↔ cold-case correlation applies a non-tunable hard filter before scoring: candidate cases must be within 50 statute miles of the subject case (PostGIS `ST_Distance(c.geom::geography, p.geom::geography) / 1609.344` for statute-mile conversion, in raw SQL) AND within ±20 years of the subject case's `incident_date`. Cases outside either window are dropped before any scoring runs.

Anchor: `src/casesignal/correlation/service.py`

**FR-019 — Weighted scoring with floor**

Surviving candidates receive a rarity-weighted score for shared weapon, location type, and demographic attributes, discounted by geographic and temporal distance. Age uses a graded similarity kernel. Scores are normalized to a 0–10 scale. A lead needs a score of at least 0.5 and at least two matched dimensions. These tunable constants live in `src/casesignal/correlation/config.py`; they are not probabilities or validation of a common offender.

Anchor: `src/casesignal/correlation/scoring.py`

**FR-020 — Top-5 with closer-distance tiebreak**

The correlation panel returns at most 5 candidates per subject case, ordered by score descending; ties are broken by closer geographic distance. The detail page renders these as a "Possibly related cases" panel with each candidate's score, distance, and date delta.

Anchor: `frontend/src/components/case-detail/RelatedCasesPanel.tsx`

## 5. Query API

**FR-021 — List endpoint filters and sort**

`GET /api/v1/cold-cases/` accepts these filter parameters (all comma-separable, all optional):
- Range: `year_min`, `year_max`
- Single-value: `city`, `state`, `q` (free-text)
- Multi-value: `case_type`, `gender`, `race`, `weapon`, `location_type`, `source_system`, `precision`

And the sort parameter `sort` against the 12-value `SortOrder` enum (`incident_date_asc`/`_desc`, `victim_name_asc`/`_desc`, `location_asc`/`_desc`, `state_asc`/`_desc`, `case_type_asc`/`_desc`, `source_case_id_asc`/`_desc`). Default sort is `incident_date_desc`. Results are paginated with `limit` (default 100, max 1000) and `offset`.

Anchor: `src/casesignal/api/routes/cold_cases.py`

**FR-022 — Map endpoint non-null geometry**

`GET /api/v1/cold-cases/map` returns only cases with non-null `cases.geom` (PostGIS geometry column populated when geocoding succeeds). All precisions (street, landmark, zip, county) are included by default — clients filter precision via the `precision` query parameter (e.g. `?precision=street,landmark` to drop county centroids that cluster artificially at the geographic county center). Visual differentiation between precisions is the frontend's responsibility (FR-031).

Anchor: `src/casesignal/api/services/cold_cases/` (`_MAP_SQL` `WHERE cases.geom IS NOT NULL`)

**FR-023 — Detail endpoint hybrid URL**

`GET /api/v1/cold-cases/{case_id}` returns the case plus its victim(s), contact row, photos, and `case_extractions` blocks at both `prompt_tier=1` and `prompt_tier=2`. The frontend uses `/cold-cases/{id}/{slug}` and handles canonical slug redirects separately from the JSON API.

Anchor: `src/casesignal/api/routes/cold_cases.py`

**FR-024 — Filter-options endpoint**

`GET /api/v1/cold-cases/filter-options` returns the DISTINCTed filter dimensions feeding the sidebar: `states`, `cities`, `case_types`, `genders`, `races`, `weapons`, `location_types`, `source_systems` (as `list[{code, name}]`), and `year_range`. It also returns a separate `dataset` block of shape `{version, last_ingested}` describing the deployed corpus snapshot. Used by both list and map surfaces to drive identical filter UIs (FR-028).

Anchor: `src/casesignal/api/services/cold_cases/`

**FR-025 — Free-text search performance**

`?q=` parameter performs case-insensitive substring search over `cases.case_name`, `cases.source_case_id`, `victim.first_name`, and `victim.last_name` via pg_trgm GIN indexes. Latency depends on the database and corpus; the historical <100 ms observation is not a CI performance guarantee. Backed by `migration 0008_pg_trgm_search_indexes.py`.

Anchor: Migration 0008

**FR-026 — Source attribution surface**

Source attribution is queryable via the `source_system` filter parameter (FR-021); each public list/map item exposes `state`, `city`, and `geocode_precision` to support source-aware investigation. Per-row exposure of `source_system_code` and `dataset_version_id` is intentionally omitted from public read-endpoint schemas (`ColdCaseListItem`, `ColdCaseMapItem`, `CaseDetailResponse`); the binding is materialized via `cases.dataset_version_id` in the schema for admin/audit pathways, and the deployed corpus snapshot is exposed once-per-page via the `dataset` block on `/filter-options` (FR-024).

Anchor: `src/casesignal/api/schemas/cold_cases.py`

**FR-027 — Total-unfiltered count**

List and map response `meta` blocks include `total_unfiltered` alongside the filtered `total`. This drives the sidebar's "X of Y" indicator so users can see how much filtering they've applied without navigating away.

Anchor: PR #36

## 6. Frontend Surfaces

**FR-028 — Shared filter sidebar**

The list page (`/cold-cases`) and map page (`/cold-cases/map`) render the same `FilterSidebar` component with all filter dimensions present on both surfaces. Filter state is mirrored in URL query params (`nuqs`) so deep-links round-trip cleanly. Changing a filter on either surface updates both views' counts.

Anchor: `frontend/src/components/filters/FilterSidebar.tsx`

**FR-029 — Detail-page reveal-source affordance**

Tier-1 and Tier-2 extracted fields on `/cold-cases/{id}/{slug}` render with a click-to-reveal interaction: clicking the extracted value highlights the corresponding span in the narrative. Spans use the `*_source_start` / `*_source_end` offsets from `case_extractions` (FR-009). Fields with NULL spans (source-MO rows per FR-010, or low-confidence rows) hide the reveal-source affordance.

Anchor: `frontend/src/components/case-detail/{MOSection,NarrativeWithHighlights,SourceRevealController}.tsx`

**FR-030 — Methodology page transparency**

`/methodology` exposes per-source disclosure cards documenting: source name + URL, license posture, ingestion method (CSV / API / scrape / Looker), record count, extraction posture (no LLM / Tier-1 / Tier-1+Tier-2), and field-completeness expectations. The methodology page is anchor-linked from the chrome footer and from the data-source badge on every case detail page.

Anchor: `frontend/src/app/methodology/page.tsx`

**FR-031 — Precision-driven pin styling**

Map markers render as 14px circles with opacity-based styling that reflects `geocode_precision` (descending visual "completeness" within the Glacier palette, no new hues): street = solid `bg-primary` with background ring; landmark = `bg-primary/80` with background ring; zip = `bg-primary/50` with background ring; county = `bg-transparent` with `ring-primary` outline (hollow puck) so lower-confidence county centroids read as visually distinct from street-level confidence. The legend explains the styling on first paint. Clients can hide low-precision pins entirely via the `precision` filter parameter (FR-022).

Anchor: `frontend/src/components/map/MarkerDivIcon.tsx`

**FR-032 — Humanized case_type rendering**

Raw `case_type` DB values (e.g., `homicide`, `suspicious_death`) render as human-readable labels (`Homicide`, `Suspicious Death`) at every surface that displays them: filter sidebar checkboxes, list cards, list table cells, case-detail hero, map marker popups, applied-filter chips. Unknown future values fall back to a snake_case → Title Case transformation rather than rendering raw.

Anchor: `frontend/src/lib/humanizeCaseType.ts`

## 7. Auth & Integrity

**FR-033 — Three-tier auth model**

The API enforces a three-tier auth model:
- **Anonymous public reads** — `GET /api/v1/cold-cases/*` and other public surfaces require no authentication; rate-limited by IP.
- **User-role API keys** — elevated routes (e.g., `/api/v1/admin/operator/*`) require an `X-Api-Key` header backed by an active `app_auth.api_keys` row with role ∈ {operator, admin}.
- **Admin role** — write/admin routes require role='admin' specifically; operator is read-elevated, admin is read+write.

The read-only operator dashboard has a separate Supabase Auth path backed by `app_auth.admin_user`. Supabase login does not authorize API-key mutation routes. Offboarding must revoke both credentials.

API keys are stored as HMAC-SHA256 fingerprints (the `csk_` prefix exposes 8 chars for log correlation; the rest hashes). `KEY_HMAC_SECRET` rotation invalidates all keys.

Anchor: PR #29 + `src/casesignal/api/dependencies/auth.py`

**FR-034 — Rate limits**

slowapi `Limiter` is installed on the FastAPI app, keyed on authenticated API key or remote IP. Tighter limits apply to write-heavy POST endpoints. Limits are per-route, configured at route-definition time.

Anchor: PR #23

**FR-035 — Per-stage status instrumentation**

Ingestion stages, extraction calls, and geocoding attempts each write a status row (`etl.ingestion_run` + `etl.ingestion_run_stage`, `cold_case.extraction_job`, `cold_case.geocoding_job`) with per-stage status ∈ {pending, running, succeeded, failed} and failure-mode notes (`error_detail` / `notes` columns). These rows are the audit surface for post-incident analysis; they are not exposed to the public API.

Anchor: Migration 0001 (ingestion_run + ingestion_run_stage + extraction_job + geocoding_job tables) + `src/casesignal/etl/services/ingestion_tracking.py`

**FR-036 — Published-only public reads**

Only dataset versions with `etl.dataset_version.ingestion_status='published'` are exposed via public read endpoints. Pending, failed, or unpublished versions stay invisible to the public API regardless of which cases they contain. Admin-tier callers can query unpublished versions via admin routes.

Anchor: `src/casesignal/api/services/cold_cases/` filters on `dataset_version.ingestion_status`

---

## 8. Source tooling

**FR-037 — Reviewed source discovery**

Source Scout separates discovery, evidence-based classification, and human acceptance. The bare CLI uses deterministic catalog discovery; it does not fabricate hosted search or classification results. County-tier discovery remains unimplemented. See [Source Scout](runbooks/source-scout.md).

**FR-038 — Isolated draft verification and branch ownership**

Adapter Drafter verifies a captured listing/detail traversal and canonical row mapping against trusted fixtures and expectations. Grading requires the documented Linux sandbox. Finish commits and pushes the claimed draft branch and validates PR identity when retrying. Offline PASS does not certify database publication. See [Adapter Drafter](runbooks/adapter-drafter.md) and its [correction spec](engineering-decisions.md).

## Appendix A — Verification

This appendix maps each FR to an automated check or test file that already exercises it. Future code reviewers and operators use this as a fast traceability lookup.

| FR | Verification |
|----|--------------|
| FR-001 | `tests/unit/etl/adapters/test_*.py` (per-adapter stage tests) + `tests/integration/test_cold_case_*_e2e.py` |
| FR-002 | `src/casesignal/etl/adapters/cold_case_oh_ag/scrape_search.py:drift_check` unit tests; live drift fires the `phase_N_verify.sh` Gate 3 |
| FR-003 | Migration 0007 backfill script + provenance checks in transform tests |
| FR-004 | Per-adapter `test_cold_case_*_county_fips.py` + the `phase_N_verify.sh` Gate that asserts FIPS coverage |
| FR-005 | `register.py` get-or-create exercised by integration tests; re-running the same source produces no new rows |
| FR-006 | Photo presence checked in `phase_N_verify.sh` Gate 4 (each phase has its own floor) |
| FR-007 | `tests/unit/test_cold_case_extractor_*.py` against fixture LLM responses |
| FR-008 | `tests/unit/test_cold_case_tier2_extractor.py` |
| FR-009 | `tests/unit/test_cold_case_tier2_extractor.py::test_unresolved_phrase_marks_low_confidence` |
| FR-010 | Phase 6 `phase_6_verify.sh` Gate 8 — 32 source-MO rows for WY |
| FR-011 | Tier-2 schema/parser review and extraction unit tests; race is absent from model output |
| FR-012 | `tests/unit/test_cold_case_tier2_extractor.py::test_dict_shaped_scalar_value_does_not_crash` (PR #81) |
| FR-013 | `tests/integration/test_cold_case_extraction_queue.py` (exception → status='failed') |
| FR-014 | `tests/unit/geocoding/test_service.py` (ladder traversal under each tier's success/failure) |
| FR-015 | Migration 0005 enforces CHECK constraint on the enum |
| FR-016 | `tests/unit/test_cold_case_persistence_geocoding_guard.py` |
| FR-017 | `tests/unit/geocoding/test_service.py::test_bare_state_skips_google_and_falls_to_county` + `::test_bare_state_code_also_skips_google` (PR #69) |
| FR-018 | `tests/integration/test_correlation_service.py` (50mi/20yr hard-filter assertions) |
| FR-019 | `tests/integration/test_correlation_service.py` + `tests/unit/test_correlation_scoring.py` |
| FR-020 | `tests/integration/test_correlation_service.py` (top-5 + distance tiebreak) |
| FR-021 | `tests/integration/test_cold_cases_list_api.py` |
| FR-022 | `tests/integration/test_cold_case_map_api.py` — every map test exercises the `WHERE cases.geom IS NOT NULL` contract by asserting result-set membership; `::test_map_precision_filter_single` + `::test_map_precision_filter_multi` cover the precision filter parameter on top of that |
| FR-023 | `tests/integration/test_cold_cases_detail_api.py` |
| FR-024 | `tests/integration/test_cold_case_filter_options.py` |
| FR-025 | `tests/integration/test_cold_cases_list_api.py::test_list_search_matches_victim_last_name` + `::test_list_search_matches_source_case_id` (pg_trgm index used; latency informally checked, not gated) |
| FR-026 | Manual verification — schema shape asserted by `ColdCaseListItem` / `ColdCaseMapItem` / `CaseDetailResponse` (`extra="forbid"`) ensures `source_system_code` / `dataset_version_id` cannot leak into public responses |
| FR-027 | `tests/integration/test_cold_cases_list_api.py::test_list_meta_includes_total_unfiltered` |
| FR-028 | `frontend/src/components/filters/FilterSidebar.test.tsx` |
| FR-029 | `frontend/src/components/case-detail/MOSection.test.tsx` + `SourceRevealController.test.tsx` |
| FR-030 | Manual check at code review (content doc, not a code path); render path validated by frontend build |
| FR-031 | `frontend/src/components/map/MarkerDivIcon.test.tsx` |
| FR-032 | `frontend/src/lib/humanizeCaseType.test.ts` |
| FR-033 | `tests/integration/test_admin_keys.py` + `tests/unit/test_route_auth.py` (PR #29) |
| FR-034 | `tests/integration/test_rate_limit_per_ip.py` + `tests/unit/test_rate_limit_client_ip.py` (PR #23) |
| FR-035 | `tests/integration/test_cold_case_extraction_queue.py::test_handle_job_marks_failed_when_llm_raises` (extraction_job.status) + `tests/integration/test_ingestion_worker.py::test_post_run_enqueues_and_worker_drives_job_to_succeeded` (ingestion_run.status); geocoding_job status — manual verification (no dedicated end-to-end test) |
| FR-036 | Manual verification — `etl.dataset_version.ingestion_status='published'` filter is enforced at `src/casesignal/api/services/cold_cases/`; covered by `tests/integration/security/test_ingestion_status_visibility.py` |

## Appendix B — Notes

- Verification entries include manual checks and historical phase gates; run the current suite in [development.md](development.md) for present behavior.
- This doc is normative for backend + frontend behavior. UI visual design (colors, typography, spacing) is governed separately by the `frontend/src/app/globals.css` design tokens and the methodology page (FR-030) describes the source posture.
- Pre-pivot requirements covering NIBRS analytics, jurisdiction comparison, and generative LLM briefings were demolished in Phase 0 (PR #45, 2026-05-08). See `CHANGELOG.md` for full demolition record.
