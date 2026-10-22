import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, ApiError } from "./api";

describe("apiFetch", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.resetAllMocks();
  });

  it("returns parsed JSON on 2xx", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const result = await apiFetch<{ ok: boolean }>("/test");
    expect(result).toEqual({ ok: true });
  });

  it("prefixes API_BASE_URL onto the path", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    await apiFetch("/x");
    expect(vi.mocked(global.fetch).mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/x",
    );
  });

  it("throws with status + path on 4xx", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("not found", { status: 404, statusText: "Not Found" }),
    );
    await expect(apiFetch("/missing")).rejects.toThrow(/404/);
    await expect(apiFetch("/missing")).rejects.toThrow(/\/missing/);
  });

  it("dev errors include statusText + body preview", async () => {
    vi.stubEnv("NODE_ENV", "development");
    try {
      vi.mocked(global.fetch).mockResolvedValue(
        new Response("detailed error body here", {
          status: 500,
          statusText: "Server Error",
        }),
      );
      await expect(apiFetch("/boom")).rejects.toThrow(/Server Error/);
      await expect(apiFetch("/boom")).rejects.toThrow(/detailed error body/);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("prod errors omit statusText + body preview", async () => {
    vi.stubEnv("NODE_ENV", "production");
    try {
      vi.mocked(global.fetch).mockResolvedValue(
        new Response("detailed error body here", {
          status: 500,
          statusText: "Server Error",
        }),
      );
      const err = (await apiFetch("/boom").catch((e) => e)) as Error;
      expect(err.message).toMatch(/500/);
      expect(err.message).toMatch(/\/boom/);
      expect(err.message).not.toMatch(/Server Error/);
      expect(err.message).not.toMatch(/detailed error body/);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("respects caller-supplied signal (overrides the 10s default)", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    const controller = new AbortController();
    await apiFetch("/x", { signal: controller.signal });
    const init = vi.mocked(global.fetch).mock.calls[0]?.[1];
    expect(init?.signal).toBe(controller.signal);
  });

  it("falls back to an AbortSignal when caller supplies none", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    await apiFetch("/x");
    const init = vi.mocked(global.fetch).mock.calls[0]?.[1];
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("wraps AbortSignal.timeout TimeoutError with path + method context", async () => {
    vi.mocked(global.fetch).mockRejectedValue(
      new DOMException("The operation timed out.", "TimeoutError"),
    );
    await expect(apiFetch("/slow")).rejects.toThrow(/timed out/);
    await expect(apiFetch("/slow")).rejects.toThrow(/\/slow/);
  });

  it("throws ApiError with .status === 404 on a 404 response", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("", { status: 404, statusText: "Not Found" }),
    );
    try {
      await apiFetch("/missing");
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);
    }
  });

  it("throws ApiError with .status === 500 on a 500 response", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("boom", { status: 500, statusText: "Server Error" }),
    );
    try {
      await apiFetch("/boom");
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(500);
    }
  });

  it("defaults to no-store when no next option is given", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    await apiFetch("/x");
    const init = vi.mocked(global.fetch).mock.calls[0]?.[1];
    expect(init?.cache).toBe("no-store");
  });

  it("does not force no-store when a next.revalidate option is given", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    await apiFetch("/x", { next: { revalidate: 3600 } });
    const init = vi.mocked(global.fetch).mock.calls[0]?.[1] as
      | (RequestInit & { next?: { revalidate?: number } })
      | undefined;
    expect(init?.cache).toBeUndefined();
    expect(init?.next?.revalidate).toBe(3600);
  });
});
