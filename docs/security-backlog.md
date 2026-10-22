# Security follow-ups

The [snapshot review](snapshot-review.md) covers repository publication scope.
Provider settings and production infrastructure were not audited by exporting
this source. Keep the following deployment checks in the operator workflow:

- Verify PostHog's provider-side **Discard client IP data** setting. Client event
  filtering does not establish server-side retention behavior.
- Verify the enforcing Content Security Policy in the deployed frontend.
  Review violations and confirm authentication, telemetry, and map requests work.
- Verify secret rotation, least-privilege IAM, backup access, and recovery drills
  in the actual deployment accounts.

## Dependency audit exceptions

### GHSA-vfj7-8cjw-p6xm: braces stack exhaustion in lint tooling

**Accepted by the project owner:** 2026-10-22. **Review by:** 2026-11-22,
or sooner when the dependency path or upstream advisory changes.

The [upstream advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
affects `braces <=3.0.3`; no patched release is available at acceptance.
Deeply nested brace patterns can exhaust the Node.js stack.

The installed path is exclusively a development dependency:
`eslint-config-next -> @next/eslint-plugin-next -> fast-glob -> micromatch -> braces`.
Verified with `pnpm why braces`; `pnpm why braces --prod` returns no path.
The lint configuration uses repository-controlled file patterns, not visitor
input. This accepts the remaining availability risk in development/CI; it
does not claim that the package is patched or safe for untrusted patterns.

`frontend/pnpm-workspace.yaml` ignores only this advisory ID. The security
workflow still audits production and development dependencies and fails on
other high/critical findings. No package-wide or severity-wide exemption is used.

At review, check the advisory and run both dependency-path commands again.
Remove the exception when a patched release can be installed or the dependency
is removed. Reassess immediately if `braces` enters a production dependency
path or is used with untrusted patterns. The review date is an operational
reminder, not an automatically enforced expiry.
