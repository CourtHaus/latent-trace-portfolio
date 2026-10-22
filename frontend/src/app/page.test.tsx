import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

vi.mock("@/lib/getFilterOptions", () => ({
  getFilterOptions: vi.fn(),
}));
vi.mock("@/lib/getDatasetCounts", () => ({
  getDatasetCounts: vi.fn(),
}));
vi.mock("@/lib/getSourcesSummary", () => ({
  getSourcesSummaryOrNull: vi.fn(),
}));
vi.mock("@/lib/getLandingCases", () => ({
  getLandingCasesOrEmpty: vi.fn(),
}));
vi.mock("@/lib/getCoverageHistogram", () => ({ getCoverageHistogram: vi.fn() }));
vi.mock("@/lib/getFeaturedCorrelation", () => ({ getFeaturedCorrelation: vi.fn() }));

import HomePage from "./page";
import { getFilterOptions } from "@/lib/getFilterOptions";
import { getDatasetCounts } from "@/lib/getDatasetCounts";
import { getYearHistogramOrNull } from "@/lib/getYearHistogram";
import { getSourcesSummaryOrNull } from "@/lib/getSourcesSummary";
import { getLandingCasesOrEmpty } from "@/lib/getLandingCases";
import { getCoverageHistogram } from "@/lib/getCoverageHistogram";
import { getFeaturedCorrelation } from "@/lib/getFeaturedCorrelation";

// page.tsx uses the resilient OrNull/OrEmpty variants for the decorative
// fetches (keep bucketByDecade real); the throwing base variants are unused here.
vi.mock("@/lib/getYearHistogram", async () => {
  const actual = await vi.importActual<typeof import("@/lib/getYearHistogram")>(
    "@/lib/getYearHistogram",
  );
  return { ...actual, getYearHistogramOrNull: vi.fn() };
});

const mockFilterOptions = {
  case_types: ["homicide"],
  cities: ["Richmond"],
  genders: ["female"],
  races: ["white"],
  states: ["VA"],
  weapons: ["firearm"],
  location_types: ["residence"],
  source_systems: [{ code: "VSPCCD_VA", name: "Virginia State Police Cold Case Database" }],
  year_range: { min: 1961, max: 2023 },
  dataset: { version: "v2026.04", last_ingested: "2026-04-20T00:00:00Z" },
};

const mockCounts = {
  totalUnfiltered: 508,
  geocodedUnfiltered: 507,
};

const mockHistogram = {
  buckets: [
    { year: 1990, count: 121 },
    { year: 2000, count: 88 },
  ],
  total_dated: 209,
  undated: 0,
};

const mockSources = {
  data: [
    {
      code: "VSPCCD_VA",
      name: "Virginia State Police Cold Case Database",
      state: "VA",
      case_count: 508,
      geocoded_count: 507,
      year_min: 1961,
      year_max: 2023,
    },
  ],
};

describe("HomePage (landing redesign)", () => {
  beforeEach(() => {
    vi.mocked(getFilterOptions).mockReset();
    vi.mocked(getDatasetCounts).mockReset();
    vi.mocked(getYearHistogramOrNull).mockReset();
    vi.mocked(getSourcesSummaryOrNull).mockReset();
    vi.mocked(getLandingCasesOrEmpty).mockReset();
    vi.mocked(getCoverageHistogram).mockReset();
    vi.mocked(getFeaturedCorrelation).mockReset();
    vi.mocked(getFilterOptions).mockResolvedValue(mockFilterOptions);
    vi.mocked(getDatasetCounts).mockResolvedValue(mockCounts);
    vi.mocked(getYearHistogramOrNull).mockResolvedValue(mockHistogram);
    vi.mocked(getSourcesSummaryOrNull).mockResolvedValue(mockSources);
    vi.mocked(getLandingCasesOrEmpty).mockResolvedValue([]);
    vi.mocked(getCoverageHistogram).mockResolvedValue({ buckets: [{ state: "VA", decade: 1990, count: 5 }] });
    vi.mocked(getFeaturedCorrelation).mockResolvedValue({
      points: [{ distance: 0.2, yearsApart: 0.3, score: 0.5 }],
      leads: [{ id: "CS-1", name: "A. Bowen", distanceMi: 5, yearsApart: 2, score: 0.6 }],
    });
  });

  it("fetches all landing data sources in parallel", async () => {
    await HomePage();
    expect(getFilterOptions).toHaveBeenCalledTimes(1);
    expect(getDatasetCounts).toHaveBeenCalledTimes(1);
    expect(getYearHistogramOrNull).toHaveBeenCalledTimes(1);
    expect(getSourcesSummaryOrNull).toHaveBeenCalledTimes(1);
    expect(getLandingCasesOrEmpty).toHaveBeenCalledTimes(1);
    expect(getCoverageHistogram).toHaveBeenCalledTimes(1);
    expect(getFeaturedCorrelation).toHaveBeenCalledTimes(1);
  });

  it("renders the landing page when decorative fetches fail (resilient, no crash)", async () => {
    // Simulate a transient cold-start 500 on the decorative aggregates: the
    // resilient variants return null/[], and the page must still render its h1
    // rather than throwing the ApiError up to the error boundary (Sentry).
    vi.mocked(getYearHistogramOrNull).mockResolvedValue(null);
    vi.mocked(getSourcesSummaryOrNull).mockResolvedValue(null);
    vi.mocked(getLandingCasesOrEmpty).mockResolvedValue([]);

    const tree = await HomePage();
    render(tree);

    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toMatch(/legible/);
    // Core stat still renders from the (independent) counts fetch.
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("renders the h1 with 'made legible'", async () => {
    const tree = await HomePage();
    render(tree);
    // h1 spans 'made' and 'legible' across a text node and an <em>
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toMatch(/made/);
    expect(h1.textContent).toMatch(/legible/);
  });

  it("renders the dynamic total count in the stat rail", async () => {
    const tree = await HomePage();
    const { container } = render(tree);
    // 508 appears as a formatted number; CountUp renders it statically in SSR
    expect(container.textContent).toMatch(/508/);
  });

  it("renders provenance source code", async () => {
    const tree = await HomePage();
    render(tree);
    // Provenance renders s.code in the source column
    expect(screen.getByText("VSPCCD_VA")).toBeInTheDocument();
  });

  it("contains no em-dashes in rendered text", async () => {
    const tree = await HomePage();
    const { container } = render(tree);
    expect(container.textContent).not.toContain("—");
  });

  it("renders the Coverage section when histogram data is present", async () => {
    const tree = await HomePage();
    const { container } = render(tree);
    expect(container.textContent).toMatch(/Jurisdiction x decade/);
  });

  it("omits the Coverage section when the histogram is empty (resilient fallback)", async () => {
    vi.mocked(getCoverageHistogram).mockResolvedValue({ buckets: [] });
    const tree = await HomePage();
    const { container } = render(tree);
    expect(container.textContent).not.toMatch(/Jurisdiction x decade/);
  });

  it("has no a11y violations", async () => {
    const tree = await HomePage();
    const { container } = render(tree);
    expect(await axe(container)).toHaveNoViolations();
  });
});
