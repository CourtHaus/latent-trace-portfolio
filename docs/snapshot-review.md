# Portfolio snapshot review

Prepared on 2026-10-22 for owner review. This is a separate repository with a
new Git history. It is not connected to production deployment. Publication
requires an explicit owner decision; the preparation creates a private repository.

## Included

Application source, schema migrations, locked dependencies, CI, synthetic tests,
current documentation, the project's logo assets with their provenance note,
and Census-derived reference tables with their source notes.

## Excluded

- All original Git objects, branches, tags, issues, PRs, Actions logs, and artifacts
- Historical database snapshots, bulk source exports, photos, and runtime data
- Agency HTML, JSON, XML, and PDF captures and recorded-model case narratives
- Capture-dependent tests and the recorded-model accuracy gate
- Dated plans, operational audits, case-level reports, and old repair scripts
- Unused landing images and historical design screenshots
- Local environment files, credentials, cloud account links, and tool sessions

The working private repository and its deployment connections remain intact.
Future updates to this snapshot must repeat the content review; never merge
private development history into this repository.

## Test scope

The retained suite exercises synthetic inputs and isolated databases. Additional
parser examples use invented records. Capture-based comparisons are deliberately
not represented as passing tests. The suite does not establish current agency
page compatibility, source completeness, model accuracy, or live provider behavior.

## Validation

The initial snapshot contains 883 files. It excludes 263 paths from the private
working tree and adds four snapshot-specific documents/tests. No original Git
objects or hosted history were copied.

Local validation completed on 2026-10-22:

- Backend: **2,338 passed, 3 skipped**, using a newly created, migrated local test
  database. The skips require an explicitly enabled live model endpoint.
- Frontend: **531 passed across 93 files**; lint, TypeScript checks, and the
  production build passed against an isolated local API.
- Ruff passed; mypy passed across 484 source/test files.
- Documentation: 26 Markdown documents passed local-link and inventory checks.
- Gitleaks scanned the exact proposed tree, including encoded content and
  archives, with default rules and **no allowlist exceptions**. No secrets found.
- Pre-commit checks passed, including private-key, large-file, YAML, and hygiene checks.
- Python dependency audit reported no known vulnerabilities. The frontend audit
  passed with the existing, owner-approved `braces` advisory exception; its
  review date is 2026-11-22. See the [security backlog](security-backlog.md).

An overlap check against excluded captures identified copied narrative examples
inside tests; those examples were replaced with invented text and revalidated.
Synthetic HTML/PDF parser tests and a synthetic Virginia CSV ingestion test
exercise representative paths without agency documents or a private corpus.
This does not reproduce every capture-based regression or accuracy measurement.

The application source is preserved apart from documentation examples and the
validation-label default path, which now points into ignored `data/validation/`.
Capture and audit utilities also write into ignored private storage by default.
CI rejects unreviewed fixture additions, archive/PDF files, and private report
paths. An ignore rule or failed CI check cannot erase an already-pushed file.

GitHub workflow results are available on the repository's Actions tab; local
results above do not imply a remote workflow completed.

## Rights

Original code remains all rights reserved; this is not an open-source license.
GitHub's platform terms still govern public viewing and forking. Third-party
components retain their own rights. The [logo provenance](../branding/DESIGN.md)
and [reference data provenance](../data/static/README.md) are preserved.

Secret scanning is pattern-based and does not prove that all sensitive information
has been identified. This review covers this snapshot, not the private repository's
hosted history or production infrastructure.
