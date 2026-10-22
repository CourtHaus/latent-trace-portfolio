import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const initMock = vi.fn();

vi.mock("@sentry/nextjs", () => ({
  init: (...args: unknown[]) => initMock(...args),
  captureRouterTransitionStart: vi.fn(),
  captureRequestError: vi.fn(),
}));

describe("observability/sentry", () => {
  beforeEach(() => {
    vi.resetModules();
    initMock.mockClear();
    delete (process.env as Record<string, string | undefined>)
      .NEXT_PUBLIC_SENTRY_DSN;
  });

  afterEach(() => {
    delete (process.env as Record<string, string | undefined>)
      .NEXT_PUBLIC_SENTRY_DSN;
  });

  it("reports disabled and does not init without a DSN", async () => {
    const { sentryEnabled, initSentryClient, initSentryServer } = await import(
      "./sentry"
    );
    expect(sentryEnabled()).toBe(false);
    initSentryClient();
    initSentryServer();
    expect(initMock).not.toHaveBeenCalled();
  });

  it("reports enabled and inits both runtimes with a DSN", async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN =
      "https://public@example.ingest.sentry.io/1";
    const { sentryEnabled, initSentryClient, initSentryServer } = await import(
      "./sentry"
    );
    expect(sentryEnabled()).toBe(true);

    initSentryClient();
    initSentryServer();
    expect(initMock).toHaveBeenCalledTimes(2);

    const opts = (initMock.mock.calls[0]?.[0] ?? {}) as Record<string, unknown>;
    expect(opts.dsn).toBe("https://public@example.ingest.sentry.io/1");
    // Sensitive-data platform: PII must never be attached by default.
    expect(opts.sendDefaultPii).toBe(false);
  });
});
