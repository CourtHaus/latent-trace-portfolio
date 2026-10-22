import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

import { getCoverageHistogram } from "./getCoverageHistogram";
import { apiFetch } from "@/lib/api";

describe("getCoverageHistogram (resilience)", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.spyOn(console, "warn").mockImplementation(() => {}); // dev fallback warn is expected
  });

  it("returns the real histogram when the fetch succeeds", async () => {
    const payload = { buckets: [{ state: "VA", decade: 1990, count: 5 }] };
    vi.mocked(apiFetch).mockResolvedValue(payload);
    expect(await getCoverageHistogram()).toEqual(payload);
  });

  it("returns an empty histogram (does not throw) when the fetch fails", async () => {
    // e.g. the backend route isn't deployed yet -> 422 from the /{case_id} catch-all.
    vi.mocked(apiFetch).mockRejectedValue(new Error("422 Unprocessable Entity"));
    expect(await getCoverageHistogram()).toEqual({ buckets: [] });
  });
});
