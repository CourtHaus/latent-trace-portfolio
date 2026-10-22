# Configuration recovery

Use provider dashboards and your private secret store to recover configuration.
Do not reconstruct secrets from Git history, logs, issues, or copied chat text.
The example environment files document names and local defaults, not credentials.

If a credential was exposed, revoke or rotate it at its provider, update each
consumer, restart affected services, and verify the old credential no longer
works. Review the exposure window and relevant provider logs. Database passwords,
Supabase service credentials, HMAC secrets, and hosted-model credentials have
separate consumers and rotation procedures.

A browser-visible map or authentication publishable key is not a server secret.
Apply provider-supported origin and usage restrictions. Never replace it with a
service-role key. Rebuild the frontend when changing build-time public settings.

Use the [deployment runbook](runbook.md) for variable placement and smoke checks.
Test restores in a fresh local database using the [restore guide](../RESTORE.md).
This snapshot cannot establish the correctness of a deployed account's settings.
