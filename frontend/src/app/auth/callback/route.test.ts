// @vitest-environment node

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";
import { getSafeNextPath } from "./nextPath";
import { GET } from "./route";

const exchangeCodeForSession = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(async () => ({
    auth: {
      exchangeCodeForSession,
    },
  })),
}));

describe("getSafeNextPath", () => {
  const origin = "https://app.example";

  it("accepts normal same-origin paths", () => {
    expect(getSafeNextPath("/admin", origin)).toBe("/admin");
  });

  it("preserves query strings and hashes for same-origin paths", () => {
    expect(getSafeNextPath("/admin?tab=ops#latest", origin)).toBe("/admin?tab=ops#latest");
  });

  it.each([
    ["external absolute URL", "https://evil.com"],
    ["protocol-relative URL", "//evil.com"],
    ["backslash path", "/\\evil.com"],
    ["encoded backslash path", "/%5Cevil.com"],
    ["malformed percent encoding", "/admin%ZZ"],
    ["origin-mismatch normalized path", "/%2F%2Fevil.com"],
  ])("falls back for %s", (_label, next) => {
    expect(getSafeNextPath(next, origin)).toBe("/admin");
  });
});

describe("GET", () => {
  beforeEach(() => {
    exchangeCodeForSession.mockReset();
  });

  it("exchanges a callback code and redirects to a sanitized same-origin path", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: null });
    const url = "https://app.example/auth/callback?code=abc&next=/admin%3Ftab%3Dops%23latest";

    const response = await GET({
      url,
      nextUrl: new URL(url),
    } as NextRequest);

    expect(exchangeCodeForSession).toHaveBeenCalledWith("abc");
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://app.example/admin?tab=ops#latest");
  });
});
