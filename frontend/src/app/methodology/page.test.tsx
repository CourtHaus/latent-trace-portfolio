import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/getFilterOptions", () => ({
  getFilterOptions: vi.fn(),
}));
vi.mock("@/lib/getDatasetCounts", () => ({
  getDatasetCounts: vi.fn(),
}));
vi.mock("@/lib/getSourcesSummary", () => ({
  getSourcesSummary: vi.fn(),
}));
vi.mock("@/lib/getCorrelationWeights", () => ({
  getCorrelationWeights: vi.fn(),
}));

import MethodologyPage from "./page";
import { getFilterOptions } from "@/lib/getFilterOptions";
import { getDatasetCounts } from "@/lib/getDatasetCounts";
import { getSourcesSummary } from "@/lib/getSourcesSummary";
import { getCorrelationWeights } from "@/lib/getCorrelationWeights";
import type { CorrelationConfigResponse } from "@/lib/getCorrelationWeights";

const mockFilterOptions = {
  case_types: ["homicide"],
  cities: ["Richmond"],
  genders: ["female"],
  races: ["white"],
  states: ["VA", "MD"],
  weapons: ["firearm"],
  location_types: ["residence"],
  source_systems: [
    { code: "VSPCCD_VA", name: "Virginia State Police Cold Case Database" },
    { code: "BCOUNTY_MD_PD", name: "Baltimore County PD Unsolved Homicides" },
  ],
  year_range: { min: 1961, max: 2024 },
  dataset: { version: "v1.0", last_ingested: "2026-05-08T00:00:00Z" },
};

const mockCounts = { totalUnfiltered: 600, geocodedUnfiltered: 580 };

const mockCorrelationWeights = {
  geo_miles: 50,
  time_years: 20,
  top_n: 5,
  smoothing_alpha: 0.5,
  // Real config defaults (correlation/config.py): half-lives 20mi / 10yr,
  // score_floor 0.5 on a 0..10 scale. Other sentinels below are arbitrary
  // wiring values, not the production constants.
  distance_half_life_miles: 20,
  time_half_life_years: 10,
  age_kernel_full_years: 2,
  age_kernel_zero_years: 10,
  age_close_years: 5,
  min_dimensions: 2,
  score_floor: 0.5,
  score_scale: 10,
  raw_max_bits: 24,
  age_close_weight_bits: 1.5,
  // Shape matches the real endpoint: examples for weapon / location_type /
  // victim_gender / victim_race only (no victim_age), raw values, and the
  // rarity label in its own field. Within each dimension the common entry
  // carries lighter bits than the rare one.
  example_weights: [
    { dimension: "weapon", value: "firearm", bits: 0.42, rarity: "common" },
    { dimension: "weapon", value: "asphyxiation", bits: 5.1, rarity: "rare" },
    {
      dimension: "location_type",
      value: "residence",
      bits: 0.88,
      rarity: "common",
    },
    {
      dimension: "location_type",
      value: "vehicle",
      bits: 3.74,
      rarity: "rare",
    },
    {
      dimension: "victim_gender",
      value: "male",
      bits: 0.51,
      rarity: "common",
    },
    {
      dimension: "victim_gender",
      value: "female",
      bits: 1.32,
      rarity: "rare",
    },
    { dimension: "victim_race", value: "white", bits: 0.97, rarity: "common" },
    { dimension: "victim_race", value: "asian", bits: 4.3, rarity: "rare" },
  ],
} satisfies CorrelationConfigResponse;

const mockSourcesSummary = {
  data: [
    {
      code: "VSPCCD_VA",
      name: "Virginia State Police Cold Case Database",
      state: "VA",
      case_count: 524,
      geocoded_count: 523,
      year_min: 1961,
      year_max: 2024,
    },
    {
      code: "BCOUNTY_MD_PD",
      name: "Baltimore County PD Unsolved Homicides",
      state: "MD",
      case_count: 75,
      geocoded_count: 75,
      year_min: 1970,
      year_max: 2024,
    },
    {
      code: "CCSO_MD_PD",
      name: "Charles County Sheriff",
      state: "MD",
      case_count: 5,
      geocoded_count: 5,
      year_min: 1990,
      year_max: 2024,
    },
    {
      code: "WICO_MD_SO",
      name: "Wicomico Sheriff",
      state: "MD",
      case_count: 6,
      geocoded_count: 6,
      year_min: 1990,
      year_max: 2024,
    },
  ],
};

describe("/methodology", () => {
  beforeEach(() => {
    vi.mocked(getFilterOptions).mockReset();
    vi.mocked(getDatasetCounts).mockReset();
    vi.mocked(getSourcesSummary).mockReset();
    vi.mocked(getCorrelationWeights).mockReset();
    vi.mocked(getFilterOptions).mockResolvedValue(mockFilterOptions);
    vi.mocked(getDatasetCounts).mockResolvedValue(mockCounts);
    vi.mocked(getSourcesSummary).mockResolvedValue(mockSourcesSummary);
    vi.mocked(getCorrelationWeights).mockResolvedValue(mockCorrelationWeights);
  });

  it("renders the page heading", async () => {
    const tree = await MethodologyPage();
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: /how the data is made/i })
    ).toBeInTheDocument();
  });

  it("includes section anchors for every numbered section", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    for (const id of [
      "preamble",
      "data-sources",
      "modus-operandi",
      "correlation",
      "geocoding-precision",
      "bias",
      "limits",
      "citation",
      "revision-history",
    ]) {
      expect(container.querySelector(`#${id}`)).not.toBeNull();
    }
  });

  it("explains the three confidence states (confident / uncertain / unknown)", async () => {
    const tree = await MethodologyPage();
    render(tree);
    expect(screen.getAllByText(/confident/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/uncertain/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/unknown/i).length).toBeGreaterThan(0);
  });

  it("frames the extraction model as locally-run with no third-party AI", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).toMatch(/locally/i);
    expect(text).toMatch(/no case data is sent to third-party/i);
  });

  it("hero stats render data-bound case totals", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    // 600 total cases (mocked) + 580 geocoded → 96.7% coverage
    expect(text).toContain("600");
    expect(text).toContain("96.7");
  });

  it("hero eyebrow shows the dataset version, not a 'working documentation' hedge", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).toMatch(/DATASET v1\.0/);
    expect(text).not.toMatch(/working documentation/i);
  });

  it("citation block uses a real origin, not a placeholder domain", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/casesignal\.example/);
    expect(text).toMatch(/\/methodology/);
  });
});

describe("/methodology — correlation section (C2)", () => {
  beforeEach(() => {
    vi.mocked(getFilterOptions).mockReset();
    vi.mocked(getDatasetCounts).mockReset();
    vi.mocked(getSourcesSummary).mockReset();
    vi.mocked(getCorrelationWeights).mockReset();
    vi.mocked(getFilterOptions).mockResolvedValue(mockFilterOptions);
    vi.mocked(getDatasetCounts).mockResolvedValue(mockCounts);
    vi.mocked(getSourcesSummary).mockResolvedValue(mockSourcesSummary);
    vi.mocked(getCorrelationWeights).mockResolvedValue(mockCorrelationWeights);
  });

  it("documents the geographic and temporal hard filters with values", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).toMatch(/50/);
    expect(text).toMatch(/miles/i);
    expect(text).toMatch(/20/);
    expect(text).toMatch(/years/i);
  });

  it("renders the live worked-example bits table from example_weights", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    // Dimension labels and the actual raw example values + bits from the mock.
    expect(text).toMatch(/weapon/i);
    expect(text).toMatch(/firearm/i);
    expect(text).toMatch(/asphyxiation/i);
    // bits formatted via toFixed(2): 0.42 and 5.1 -> "5.10".
    expect(text).toContain("0.42");
    expect(text).toContain("5.10");
  });

  it("labels each worked-example value as common or rare and glosses the bits", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    // The rarity contrast must render as readable tags, not live only in bits.
    expect(text).toMatch(/\bcommon\b/i);
    expect(text).toMatch(/\brare\b/i);
    // Plain-language gloss connecting bits to "rarer = counts more".
    expect(text).toMatch(/bits measure rarity/i);
    expect(text).toMatch(/twice as rare/i);
  });

  it("explains rarity weighting and smoothing by alpha without jargon", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).toMatch(/rarer shared characteristics count for more/i);
    // The named term "Laplace smoothing" is intentionally dropped; the
    // consequence (no unbounded weight) stays.
    expect(text).not.toMatch(/laplace/i);
    expect(text).toMatch(/doesn['’]t earn an unbounded weight/i);
    // smoothing_alpha still cited by value from config (0.5).
    expect(text).toContain("0.5");
  });

  it("documents the proximity half-life discount with config values", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).toMatch(/half-weight discount/i);
    expect(text).toMatch(/20 miles/i);
    expect(text).toMatch(/10 years/i);
  });

  it("states the lead rules: score floor, min dimensions, top-n, distance tiebreak", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    // score_floor 0.5 on a 0..score_scale 10 scale, min_dimensions 2, top_n 5.
    expect(text).toMatch(/0 to 10/i);
    expect(text).toMatch(/at least\s*2/i);
    expect(text).toMatch(/closer distance breaking ties/i);
  });

  it("renders the bounded validation note (ranking aid, no ground-truth claim)", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).toMatch(/no public dataset records which cold cases are truly linked/i);
    expect(text).toMatch(/does not assert that two cases are connected/i);
  });

  it("explains that unknown classifications exclude that dimension from scoring", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    expect(container.textContent ?? "").toMatch(
      /excludes that dimension from scoring/i
    );
  });

  it("explains low-confidence MO classifications still count as matches", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    expect(container.textContent ?? "").toMatch(
      /still counts as a match for scoring purposes/i
    );
  });

  it("scopes correlation to cold-case ↔ cold-case within the same dataset", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    expect(container.textContent ?? "").toMatch(
      /cold cases to other cold cases within the same dataset/i
    );
  });
});

describe("/methodology — coverage table (D1)", () => {
  beforeEach(() => {
    vi.mocked(getFilterOptions).mockReset();
    vi.mocked(getDatasetCounts).mockReset();
    vi.mocked(getSourcesSummary).mockReset();
    vi.mocked(getCorrelationWeights).mockReset();
    vi.mocked(getFilterOptions).mockResolvedValue(mockFilterOptions);
    vi.mocked(getDatasetCounts).mockResolvedValue(mockCounts);
    vi.mocked(getSourcesSummary).mockResolvedValue(mockSourcesSummary);
    vi.mocked(getCorrelationWeights).mockResolvedValue(mockCorrelationWeights);
  });

  it("renders a state row for every covered state", async () => {
    const tree = await MethodologyPage();
    render(tree);
    // Virginia row collapsed by default; the summary header text is rendered.
    expect(screen.getByText("Virginia")).toBeInTheDocument();
    expect(screen.getByText("Maryland")).toBeInTheDocument();
  });

  it("annotates the Maryland row with the sub-state jurisdictions count", async () => {
    const tree = await MethodologyPage();
    render(tree);
    // The text appears in two places: the always-visible row chip
    // "(6 of 24 jurisdictions)" and the expanded MD panel "6 of 24
    // jurisdictions". Both are part of the DOM; assert at least one match.
    expect(screen.getAllByText(/6 of 24 jurisdictions/i).length).toBeGreaterThan(0);
  });

  it("includes a coverage map labelled for screen readers", async () => {
    const tree = await MethodologyPage();
    render(tree);
    expect(
      screen.getByRole("img", { name: /US map showing Latent Trace coverage/i }),
    ).toBeInTheDocument();
  });

  it("renders the per-source completeness matrix with field column headers", async () => {
    const tree = await MethodologyPage();
    render(tree);
    // Field labels chosen for the new compact matrix.
    for (const label of ["Name", "Date", "Gender", "Race", "Weapon", "Photo"]) {
      expect(screen.getByRole("columnheader", { name: label })).toBeInTheDocument();
    }
  });
});

describe("/methodology — bias & revision history (Phase 3)", () => {
  beforeEach(() => {
    vi.mocked(getFilterOptions).mockReset();
    vi.mocked(getDatasetCounts).mockReset();
    vi.mocked(getSourcesSummary).mockReset();
    vi.mocked(getCorrelationWeights).mockReset();
    vi.mocked(getFilterOptions).mockResolvedValue(mockFilterOptions);
    vi.mocked(getDatasetCounts).mockResolvedValue(mockCounts);
    vi.mocked(getSourcesSummary).mockResolvedValue(mockSourcesSummary);
    vi.mocked(getCorrelationWeights).mockResolvedValue(mockCorrelationWeights);
  });

  it("names the major selection effects in the bias section", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    const text = container.textContent ?? "";
    expect(text).toMatch(/publication bias/i);
    expect(text).toMatch(/geographic coverage follows publishers/i);
    expect(text).toMatch(/skews to still-unsolved/i);
  });

  it("renders a dated revision history", async () => {
    const tree = await MethodologyPage();
    const { container } = render(tree);
    // At least one ISO-dated <time> entry in the revision log.
    const times = container.querySelectorAll("time[datetime]");
    expect(times.length).toBeGreaterThan(0);
  });
});
