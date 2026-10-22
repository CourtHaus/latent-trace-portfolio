# Contributing

Latent Trace is maintained by Courtney Hammond. The original code is
[all rights reserved](LICENSE), not open source. Public visibility does not
grant a general reuse license. Contact
[courtney@latenttrace.org](mailto:courtney@latenttrace.org) to discuss permission
before adapting or distributing the code, or contributing substantial code.
Do not submit code you lack permission to share. No copyright assignment or
broader reuse permission is implied by this guide.

Bug reports and suggestions are welcome. Follow the [code of conduct](CODE_OF_CONDUCT.md)
and use [private reporting](SECURITY.md) for vulnerabilities. Case corrections,
removal requests, and personal information belong in email, not GitHub issues.

## Working on an authorized change

1. Start with the [development guide](docs/development.md) and a branch from
   `main`. Keep unrelated changes separate.
2. Read the [architecture](docs/architecture.md) and the relevant current
   runbook. Dated plans preserve design history; they are not setup instructions.
3. Use synthetic data for new tests wherever practical. Review fixture
   [provenance and handling](tests/fixtures/README.md) before recording pages.
4. Add regression tests for behavior changes. Run the relevant checks in the
   development guide; do not run database tests against an operator corpus.
5. Update affected current documentation and `CHANGELOG.md`. Explain the
   problem, resulting behavior, validation, and remaining limitations in the PR.

CI covers backend checks on Python 3.11 and 3.12, frontend checks on Node 22,
a production build, dependency audits, and secret scanning. A successful
preview deployment alone does not mean CI passed. Do not bypass a failed
security gate by adding a broad ignore or lowering the severity threshold.

## Source adapters and AI-assisted work

New sources need provenance, a source-access review, parser fixtures, and a
human review of canonical output. Follow the [Source Scout](docs/runbooks/source-scout.md)
and [Adapter Drafter](docs/runbooks/adapter-drafter.md) runbooks. Passing an
offline drafter check is not approval to publish a dataset.

AI-generated patches need the same review and tests as handwritten changes.
Describe material generated code and how its behavior was verified. Keep
provider credentials, agent transcripts, database exports, and captured
operational data out of commits. Hosted assistants may receive supplied
source material; review that transfer before running them.
