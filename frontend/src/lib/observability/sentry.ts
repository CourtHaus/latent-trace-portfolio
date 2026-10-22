import * as Sentry from "@sentry/nextjs";

/**
 * Shared Sentry configuration for the Next.js app (client + server runtimes).
 *
 * Fully OPT-IN: with NEXT_PUBLIC_SENTRY_DSN unset (the default), init is a
 * no-op, so local dev, tests, and preview deploys without a DSN run Sentry-free.
 * The DSN is a public ingest key (not a secret), so NEXT_PUBLIC_ exposure is
 * intentional and lets one var configure both runtimes.
 */

export function sentryEnabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);
}

function commonOptions(): Sentry.NodeOptions & Sentry.BrowserOptions {
  return {
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    environment:
      process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? process.env.NODE_ENV,
    // Errors are captured for free; performance traces cost quota, so default
    // to off and let it be opt-in via env on a self-funded project.
    tracesSampleRate: Number(
      process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? "0",
    ),
    // This platform surfaces sensitive case data; never attach PII/user input
    // by default.
    sendDefaultPii: false,
  };
}

export function initSentryClient(): void {
  if (!sentryEnabled()) return;
  Sentry.init(commonOptions());
}

export function initSentryServer(): void {
  if (!sentryEnabled()) return;
  Sentry.init(commonOptions());
}
