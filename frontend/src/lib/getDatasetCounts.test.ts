import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

import { getDatasetCounts } from "./getDatasetCounts";
import { apiFetch } from "@/lib/api";

describe("getDatasetCounts", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("fetches list + map totals in parallel", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/v1/cold-cases?limit=1") {
        return { meta: { total: 508, total_unfiltered: 508, offset: 0, limit: 1 }, data: [] };
      }
      if (path === "/api/v1/cold-cases/map?limit=1") {
        return {
          meta: { bbox: null, returned: 1, truncated: true, total_unfiltered: 507 },
          data: [],
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const result = await getDatasetCounts();
    expect(result).toEqual({ totalUnfiltered: 508, geocodedUnfiltered: 507 });
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(apiFetch).mock.calls[0]?.[0]).toBe("/api/v1/cold-cases?limit=1");
    expect(vi.mocked(apiFetch).mock.calls[1]?.[0]).toBe("/api/v1/cold-cases/map?limit=1");
  });
});
