import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

const initMock = vi.fn();
const captureMock = vi.fn();
const optOutMock = vi.fn();
const hasOptedOutMock = vi.fn(() => false);

vi.mock("posthog-js", () => ({
  default: {
    init: initMock,
    capture: captureMock,
    opt_out_capturing: optOutMock,
    has_opted_out_capturing: hasOptedOutMock,
    __loaded: false,
  },
}));

describe("analytics/client", () => {
  beforeEach(() => {
    vi.resetModules();
    initMock.mockClear();
    captureMock.mockClear();
    optOutMock.mockClear();
    hasOptedOutMock.mockReturnValue(false);
    window.localStorage.clear();
    delete (process.env as Record<string, string | undefined>).NEXT_PUBLIC_POSTHOG_KEY;
    delete (process.env as Record<string, string | undefined>).NEXT_PUBLIC_POSTHOG_HOST;
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("does not init when NEXT_PUBLIC_POSTHOG_KEY is missing", async () => {
    const { initAnalytics } = await import("./client");
    initAnalytics();
    expect(initMock).not.toHaveBeenCalled();
  });

  it("does not init when opted out via localStorage", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    window.localStorage.setItem("cs_analytics_optout", "true");
    const { initAnalytics } = await import("./client");
    initAnalytics();
    expect(initMock).not.toHaveBeenCalled();
  });

  it("inits with privacy-preserving config when key is set", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    process.env.NEXT_PUBLIC_POSTHOG_HOST = "https://us.i.posthog.com";
    const { initAnalytics } = await import("./client");
    initAnalytics();
    expect(initMock).toHaveBeenCalledOnce();
    const [key, opts] = initMock.mock.calls[0]!;
    expect(key).toBe("phc_test");
    expect(opts).toMatchObject({
      api_host: "https://us.i.posthog.com",
      autocapture: false,
      capture_pageview: false,
      disable_session_recording: true,
      person_profiles: "identified_only",
      persistence: "localStorage",
    });
  });

  it("track() is a no-op if not initialized", async () => {
    const { track } = await import("./client");
    track("page_viewed", { path: "/" });
    expect(captureMock).not.toHaveBeenCalled();
  });

  it("track() forwards event + props when initialized", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    const mod = await import("./client");
    mod.initAnalytics();
    mod.track("page_viewed", { path: "/cold-cases" });
    expect(captureMock).toHaveBeenCalledWith("page_viewed", { path: "/cold-cases" });
  });

  it("track() is a no-op after localStorage opt-out, even when initialized", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    const mod = await import("./client");
    mod.initAnalytics();
    captureMock.mockClear();
    window.localStorage.setItem("cs_analytics_optout", "true");
    mod.track("page_viewed", { path: "/" });
    expect(captureMock).not.toHaveBeenCalled();
  });

  it("track() swallows posthog errors instead of throwing", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    captureMock.mockImplementationOnce(() => {
      throw new Error("posthog network error");
    });
    const mod = await import("./client");
    mod.initAnalytics();
    expect(() => mod.track("page_viewed", { path: "/" })).not.toThrow();
  });

  it("optOut() captures the opt-out event BEFORE telling posthog to stop", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    const callOrder: string[] = [];
    captureMock.mockImplementation((event: string) => {
      callOrder.push(`capture:${event}`);
    });
    optOutMock.mockImplementation(() => {
      callOrder.push("opt_out_capturing");
    });
    const { initAnalytics, optOut } = await import("./client");
    initAnalytics();
    optOut();
    const captureIdx = callOrder.findIndex((c) => c === "capture:analytics_opted_out");
    const optOutIdx = callOrder.findIndex((c) => c === "opt_out_capturing");
    expect(captureIdx).toBeGreaterThanOrEqual(0);
    expect(optOutIdx).toBeGreaterThanOrEqual(0);
    expect(captureIdx).toBeLessThan(optOutIdx);
  });

  it("optOut() persists the choice in localStorage", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    const { initAnalytics, optOut } = await import("./client");
    initAnalytics();
    optOut();
    expect(window.localStorage.getItem("cs_analytics_optout")).toBe("true");
    expect(optOutMock).toHaveBeenCalled();
  });
});


describe("analytics event privacy boundary", () => {
  it("drops SDK URLs, initial-person metadata, and arbitrary caller fields", async () => {
    const { sanitizeAnalyticsEvent } = await import("./client");
    const result = sanitizeAnalyticsEvent({ uuid: "test-event-id",
      event: "filter_applied",
      $set: { email: "private@example.test" },
      $set_once: { $initial_current_url: "https://example.test/?q=private" },
      properties: {
        token: "phc_public_test",
        distinct_id: "anonymous-test-id",
        filter_key: "weapon",
        filter_value: "private-search",
        $current_url: "https://example.test/cold-cases?q=private-search",
        $referrer: "https://example.test/?token=private",
        $set_once: { $initial_current_url: "https://example.test/?q=private" },
      },
    });
    expect(result).not.toHaveProperty("$set");
    expect(result).not.toHaveProperty("$set_once");
    expect(result?.properties).toEqual({
      token: "phc_public_test", distinct_id: "anonymous-test-id", filter_key: "weapon",
      $process_person_profile: false, $geoip_disable: true,
    });
  });

  it("removes querystrings and identifying case slugs from page paths", async () => {
    const { sanitizeAnalyticsEvent } = await import("./client");
    expect(sanitizeAnalyticsEvent({ uuid: "test-event-id",
      event: "page_viewed", properties: { path: "/cold-cases/123/example-person?q=private#detail" },
    })?.properties.path).toBe("/cold-cases/[id]/[slug]");
    expect(sanitizeAnalyticsEvent({ uuid: "test-event-id",
      event: "page_viewed", properties: { path: "/cold-cases?q=private" },
    })?.properties.path).toBe("/cold-cases");
    expect(sanitizeAnalyticsEvent({ uuid: "test-event-id",
      event: "page_viewed", properties: { path: "/unexpected-private-path" },
    })?.properties.path).toBe("/other");
  });

  it("rejects auth routes, unknown automatic events, and null events", async () => {
    const { sanitizeAnalyticsEvent } = await import("./client");
    for (const path of ["/admin", "/admin/login", "/auth/callback?code=private"]) {
      expect(sanitizeAnalyticsEvent({ uuid: "test-event-id", event: "page_viewed", properties: { path } })).toBeNull();
    }
    expect(sanitizeAnalyticsEvent({ uuid: "test-event-id", event: "$autocapture", properties: {} })).toBeNull();
    expect(sanitizeAnalyticsEvent({ uuid: "test-event-id", event: "constructor", properties: {} })).toBeNull();
    expect(sanitizeAnalyticsEvent(null)).toBeNull();
  });

  it("installs the sanitizer after SDK event enrichment", async () => {
    window.localStorage.clear();
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_test";
    vi.resetModules();
    initMock.mockClear();
    const { initAnalytics, sanitizeAnalyticsEvent } = await import("./client");
    initAnalytics();
    expect(initMock.mock.calls[0]?.[1].before_send).toBe(sanitizeAnalyticsEvent);
  });
});
