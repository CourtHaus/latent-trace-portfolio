import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/getFilterOptions", () => ({
  getFilterOptionsOrNull: vi.fn(),
}));

import { StatusStrip } from "./StatusStrip";
import { getFilterOptionsOrNull } from "@/lib/getFilterOptions";

const mockResponse = {
  case_types: ["homicide"],
  cities: ["Richmond"],
  genders: ["female"],
  races: ["white"],
  states: ["VA", "TN"],
  weapons: ["firearm"],
  location_types: ["residence"],
  source_systems: [{ code: "VSPCCD_VA", name: "Virginia State Police Cold Case Database" }],
  year_range: { min: 1961, max: 2023 },
  dataset: {
    version: "v2026.04",
    last_ingested: "2026-04-20T10:00:00Z",
  },
};

describe("StatusStrip", () => {
  beforeEach(() => {
    vi.mocked(getFilterOptionsOrNull).mockReset();
    vi.mocked(getFilterOptionsOrNull).mockResolvedValue(mockResponse);
  });

  it("renders LIVE indicator and dataset version", async () => {
    const tree = await StatusStrip();
    render(tree);
    expect(screen.getByText(/LIVE/)).toBeInTheDocument();
    expect(screen.getByText(/DATASET v2026\.04/)).toBeInTheDocument();
  });

  it("renders state list", async () => {
    const tree = await StatusStrip();
    render(tree);
    expect(screen.getByText(/VA, TN/)).toBeInTheDocument();
  });

  it("renders last-ingested relative time", async () => {
    vi.setSystemTime(new Date("2026-04-23T12:00:00Z"));
    const tree = await StatusStrip();
    render(tree);
    expect(screen.getByText(/3d ago/i)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("fetches filter-options once", async () => {
    await StatusStrip();
    expect(getFilterOptionsOrNull).toHaveBeenCalledTimes(1);
  });

  it("renders placeholders when the API is unreachable (prerender / outage)", async () => {
    vi.mocked(getFilterOptionsOrNull).mockResolvedValue(null);
    const tree = await StatusStrip();
    render(tree);
    expect(screen.getByText(/DATASET n\/a/)).toBeInTheDocument();
    expect(screen.getByText(/0 states/)).toBeInTheDocument();
  });
});
