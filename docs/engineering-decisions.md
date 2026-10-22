# Engineering decisions

These notes describe the source in this snapshot. They are an overview for
reviewers, not a claim that every production workflow has been independently
validated. See the [architecture](architecture.md) for component boundaries.

## Separate ingestion from serving

Source adapters share a staged pipeline: acquire input, register its dataset,
load raw records, transform into canonical tables, normalize, and publish.
Retaining raw and canonical representations makes transformations inspectable
and allows a correction to be replayed. It adds schema and operational work;
source changes still require parser maintenance and review.

Workers claim queued ingestion, extraction, and geocoding jobs in PostgreSQL.
`FOR UPDATE SKIP LOCKED` allows multiple workers to claim different jobs. Job
status and error records make failures visible without making a public HTTP
request wait for a full ingestion run.

## Preserve uncertainty and provenance

The application distinguishes agency fields from model-extracted values and
geographic approximations. Extraction keeps supporting narrative spans.
Missing evidence stays missing; race is not inferred from narratives or names.
Geocoding precision accompanies coordinates so a county centroid cannot be
mistaken for a known incident address.

## Treat correlations as review aids

The correlation layer scores shared characteristics with rarity weighting and
geographic and temporal filters. It does not estimate the probability of a
shared offender. Source coverage, missing data, and extraction error affect
rankings. Human review and the original agency record remain necessary.

## Constrain generated adapters

Source Scout identifies candidates. Adapter Drafter captures a fetch graph,
separates trusted reader expectations from generated code, and grades against
host-owned fixture copies and hashes. Its production adapter traverses the
captured listing/detail patterns and joins detail fields before mapping records.

Linux Landlock and seccomp constrain generated-code verification. A verifier
PASS is evidence about the captured sample and canonical mapping. It does not
certify production persistence, legal source access, or live model behavior.
Branch ownership and retry logic are tested with local Git remotes; external
provider and database pilots remain operator responsibilities. See the
[drafter runbook](runbooks/adapter-drafter.md).

## Keep tests away from the operational corpus

The test harness forces a dedicated database URL and requires a test sentinel
before collection. Tests create their own records. The snapshot includes
synthetic regression tests; agency capture comparisons and the recorded-model
accuracy benchmark stay private. Passing this suite is not a current-source
coverage or model-accuracy claim.

## Keep deployment configuration external

The frontend, API, authentication, storage, telemetry, maps, and optional hosted
models cross separate trust boundaries. Public browser keys are distinct from
server credentials. The snapshot includes configuration templates, not account
settings. Provider retention and access controls require operator verification.
