import { afterEach, describe, expect, it, vi } from "vitest";

describe("healthz route", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("returns 503 when API_BASE_URL is missing", async () => {
    vi.stubEnv("API_BASE_URL", "");

    const { GET } = await import("./route");
    const res = await GET();
    const body = await res.json();

    expect(res.status).toBe(503);
    expect(body.status).toBe("error");
  });

  it("returns 503 when API health responds non-2xx", async () => {
    vi.stubEnv("API_BASE_URL", "http://127.0.0.1:8000");
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));

    const { GET } = await import("./route");
    const res = await GET();
    const body = await res.json();

    expect(res.status).toBe(503);
    expect(body.reason).toMatch(/api 500/);
  });

  it("returns 200 when API health is ok", async () => {
    vi.stubEnv("API_BASE_URL", "http://127.0.0.1:8000");
    global.fetch = vi.fn().mockResolvedValue(new Response('{"status":"ok"}', { status: 200 }));

    const { GET } = await import("./route");
    const res = await GET();
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.status).toBe("ok");
  });
});
