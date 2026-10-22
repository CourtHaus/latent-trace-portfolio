// Client-side Sentry init (Next.js instrumentation-client convention).
// No-op unless NEXT_PUBLIC_SENTRY_DSN is set — see src/lib/observability/sentry.ts.
import * as Sentry from "@sentry/nextjs";

import { initSentryClient } from "@/lib/observability/sentry";

initSentryClient();

// Captures client-side navigation as Sentry transactions (safe no-op when
// Sentry is dormant).
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
