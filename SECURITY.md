# Security policy

Latent Trace is pre-1.0. Security fixes target the latest `main`; older commits
and tags do not have a separate maintenance commitment.

## Report privately

Email [courtney@latenttrace.org](mailto:courtney@latenttrace.org), or use
[GitHub private vulnerability reporting](https://github.com/CourtHaus/latent-trace-portfolio/security/advisories/new)
if available. Do not open a public issue or PR containing exploit details or
credentials. Include the affected commit, impact, and a minimal reproduction
using synthetic data. Please allow time for triage before public disclosure.
This is an independently maintained project with no guaranteed response time.

Reports about the API, frontend, authentication, ingestion, extraction,
geocoding, source tooling, supply chain, and accidental data exposure are
welcome. Report relevant dependency vulnerabilities even if a scanner has
already identified them. Do not access other people's data or run disruptive
tests against the live service; reproduce locally where possible.

## Repository controls

- Gitleaks checks commits and pre-commit hooks detect secrets and private keys.
  Exceptions must identify a specific known benign value and file scope.
- CI audits the locked Python and frontend dependencies. Existing exceptions
  and review dates are recorded in the [security backlog](docs/security-backlog.md).
- `.env` files, operator data, database backups, and agent runtime artifacts
  are excluded from version control. An ignore rule does not remove history.
- Browser configuration uses publishable keys only. Database passwords, API
  admin keys, HMAC secrets, and Supabase service-role keys stay server-side.

If a real credential is exposed, revoke or rotate it at its provider first.
Deleting a file or rewriting Git history does not invalidate the credential.
See [environment recovery](docs/deploy/environment-recovery.md).

The [publication review](docs/snapshot-review.md) records
the scope and limits of the repository review. A clean secret scan is not a
guarantee that a repository contains no sensitive information.
