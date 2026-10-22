# Latent Trace documentation

This is a curated source snapshot for portfolio review. Start with the
[project overview](../README.md) and [snapshot scope](snapshot-review.md).
The [inventory](documentation-inventory.md) lists the included documents.

## Understand the project

- [Architecture](architecture.md): components, data flow, and trust boundaries
- [Engineering decisions](engineering-decisions.md): design choices and tradeoffs
- [Requirements](requirements.md): behavior and verification references
- [Local development](development.md) and [frontend setup](../frontend/README.md)

## Operator references

- [Deployment](deploy/runbook.md), [configuration recovery](deploy/environment-recovery.md), and [backup and restore](RESTORE.md)
- [Source Scout](runbooks/source-scout.md) and [Adapter Drafter](runbooks/adapter-drafter.md)

These are reference instructions for authorized operators. This repository has
no production deployment connection or bundled production credentials.

## Policies

- [Data and privacy](data-and-privacy.md), [fixture scope](../tests/fixtures/README.md), and [reference data provenance](../data/static/README.md)
- [Security](../SECURITY.md) and [security follow-ups](security-backlog.md)
- [Support](../SUPPORT.md), [contributions](../CONTRIBUTING.md), and [conduct](../CODE_OF_CONDUCT.md)
- [Rights notice](../LICENSE), [brand provenance](../branding/DESIGN.md), and [changelog](../CHANGELOG.md)

Historical plans, private audits, case captures, and operational reports are
not distributed here. Regenerate the inventory after documentation changes:
`python3 scripts/check_repository_docs.py --write-inventory`.
