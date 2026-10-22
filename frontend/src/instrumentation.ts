// Server + edge runtime instrumentation (Next.js convention). Sentry init is a
// no-op unless NEXT_PUBLIC_SENTRY_DSN is set — see src/lib/observability/sentry.ts.
import * as Sentry from "@sentry/nextjs";

export async function register(): Promise<void> {
  const { initSentryServer } = await import("@/lib/observability/sentry");
  initSentryServer();
}

// Capture errors thrown in Server Components, route handlers, and middleware
// (safe no-op when Sentry is dormant).
export const onRequestError = Sentry.captureRequestError;
