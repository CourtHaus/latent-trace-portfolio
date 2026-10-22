import { describe, it, expect, vi } from "vitest";

vi.mock("./api", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./api";
import { getOperatorSnapshot } from "./operatorSnapshot";

describe("getOperatorSnapshot", () => {
  it("calls the operator API with a Supabase bearer token", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ system: { health: "healthy" } });
    await getOperatorSnapshot("token-123");
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/operator/snapshot", {
      headers: { Authorization: "Bearer token-123" },
    });
  });
});
