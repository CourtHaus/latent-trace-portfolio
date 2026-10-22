# API load test

This k6 scenario ramps to 200 virtual users, holds for one minute, then ramps
down. Run it only against a local or staging API you are authorized to stress.
It can consume hosting quota and affect other users; do not aim it at the
public service as a routine development check.

Install k6 and use a dedicated target:

```bash
k6 run -e BASE_URL=http://127.0.0.1:8000 tools/loadtest/spike.js
```

[spike.js](spike.js) defines thresholds: request failures below 1%, p95 below
800 ms for the repeated-view group, and below 3,000 ms for filtered views.
The `cached`/`uncached` labels describe the request mix; they do not prove a
response actually came from a cache. Measure cache behavior separately.

Watch API errors, CPU, connection usage, database latency, and instance count.
Record the commit, corpus size, cache state, environment, and observed results.
These thresholds are test targets, not a performance guarantee for production.
After an operator sync, use the configured cache revalidation mechanism from
the [deployment runbook](../../docs/deploy/runbook.md).
