import { afterEach, describe, expect, it, vi } from "vitest";

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({
  revalidatePath: (...args: unknown[]) => revalidatePath(...args),
}));

function postReq(headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/revalidate", { method: "POST", headers });
}

describe("POST /api/revalidate", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    revalidatePath.mockReset();
  });

  it("returns 503 and does not revalidate when REVALIDATE_SECRET is unset", async () => {
    vi.stubEnv("REVALIDATE_SECRET", "");
    const { POST } = await import("./route");
    const res = await POST(postReq({ "x-revalidate-secret": "anything" }));
    expect(res.status).toBe(503);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("returns 401 when the secret is missing", async () => {
    vi.stubEnv("REVALIDATE_SECRET", "s3cr3t");
    const { POST } = await import("./route");
    const res = await POST(postReq());
    expect(res.status).toBe(401);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("returns 401 when the secret is wrong", async () => {
    vi.stubEnv("REVALIDATE_SECRET", "s3cr3t");
    const { POST } = await import("./route");
    const res = await POST(postReq({ "x-revalidate-secret": "wrong" }));
    expect(res.status).toBe(401);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("revalidates the site with the correct secret", async () => {
    vi.stubEnv("REVALIDATE_SECRET", "s3cr3t");
    const { POST } = await import("./route");
    const res = await POST(postReq({ "x-revalidate-secret": "s3cr3t" }));
    const body = await res.json();
    expect(res.status).toBe(200);
    expect(body.revalidated).toBe(true);
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
  });
});
