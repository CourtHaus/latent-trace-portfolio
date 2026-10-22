import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/cold-cases/map",
}));

// Mock the dynamic map leaf — we're testing the wrapper, not the leaflet tree.
vi.mock("./MapLeaflet", () => ({
  MapLeaflet: vi.fn(() => <div data-testid="map-leaflet-stub" />),
}));

// Mock next/dynamic to return a component that directly renders the mock MapLeaflet.
// next/dynamic is mocked so that any dynamic(() => import("./MapLeaflet")) call
// returns a synchronous wrapper — no Suspense / Promise involved in tests.
// We render via JSX (createElement) so React calls the fn with (props, ref/undefined),
// which satisfies the toHaveBeenCalledWith(..., expect.anything()) assertions.
vi.mock("next/dynamic", async () => {
  const { createElement } = await import("react");
  const mapLeafletMod = await import("./MapLeaflet");
  return {
    default: (_importFn: unknown) => {
      return (props: Record<string, unknown>) =>
        createElement(mapLeafletMod.MapLeaflet as unknown as React.ComponentType<Record<string, unknown>>, props);
    },
  };
});

import { ClientMap } from "./ClientMap";
import * as MapLeafletMod from "./MapLeaflet";

const sampleCase = {
  case_id: 42,
  slug: "jane-doe-richmond-va-1998",
  source_case_id: "2022-0003209",
  case_name: "Augusta County - Case: 2022-0003209 - Jane Doe",
  case_type: "homicide",
  incident_date: "1998-05-14",
  latitude: 37.54,
  longitude: -77.43,
  state: "VA",
  city: "Richmond",
  victim_primary_name: "Jane Doe",
  victim_genders: ["Female"],
  victim_races: ["White"],
  geocode_precision: null,
};

const filterOptionsSample = {
  case_types: ["homicide"],
  cities: ["Richmond"],
  genders: ["Female"],
  races: ["White"],
  states: ["VA"],
  weapons: ["firearm", "knife"],
  location_types: ["residence", "public_outdoor"],
  source_systems: [{ code: "VSPCCD_VA", name: "Virginia State Police Cold Case Database" }],
  year_range: { min: 1958, max: 2023 },
  dataset: { version: "v0", last_ingested: "2026-04-21T00:00:00Z" },
};

function renderWithNuqs(ui: React.ReactElement) {
  return render(ui, { wrapper: ({ children }) => <NuqsTestingAdapter>{children}</NuqsTestingAdapter> });
}

describe("ClientMap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the filter sidebar + the map leaf stub", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^filters$/i }));
    expect(screen.getByRole("complementary", { name: /cold case map/i })).toBeInTheDocument();
    expect(screen.getByTestId("map-leaflet-stub")).toBeInTheDocument();
  });

  it("uses filterOptions prop for sidebar options (not derived from initialData)", () => {
    const filterOptions = {
      case_types: ["homicide", "missing-person"],
      cities: ["Richmond", "Norfolk"],
      genders: ["Female", "Male"],
      races: ["White", "Unknown"],
      states: ["VA"],
      weapons: ["firearm"],
      location_types: ["residence"],
      source_systems: [{ code: "VSPCCD_VA", name: "Virginia State Police Cold Case Database" }],
      year_range: { min: 1958, max: 2023 },
      dataset: { version: "v0", last_ingested: "2026-04-21T00:00:00Z" },
    };

    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptions}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /^filters$/i }));
    expect(screen.getByLabelText("Female")).toBeInTheDocument();
    expect(screen.getByLabelText("Male")).toBeInTheDocument();
    expect(screen.getByLabelText("White")).toBeInTheDocument();
    expect(screen.getByLabelText("Unknown")).toBeInTheDocument();
    expect(screen.getByLabelText("Homicide")).toBeInTheDocument();
    expect(screen.getByLabelText("Missing-person")).toBeInTheDocument();
  });

  it("shows the cluster/point mode in the stat chips", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
        mapped={400}
        coverageTotal={508}
        unresolved={108}
      />,
    );
    expect(screen.getByText(/Point mode/)).toBeInTheDocument();
    // The mapped count (400) appears in both the title block and the stat chip.
    expect(screen.getAllByText(/400/)).toHaveLength(2);
  });

  it("opens the desktop filter drawer from the Filters trigger", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    // Title visible, sidebar not yet mounted.
    expect(screen.getByRole("heading", { name: /the case map/i })).toBeInTheDocument();
    // Desktop "Filters" trigger (distinct from the mobile "Open filters" button).
    fireEvent.click(screen.getByRole("button", { name: /^filters$/i }));
    expect(screen.getByRole("complementary", { name: /cold case map/i })).toBeInTheDocument();
  });

  it("desktop filter drawer is a labelled dialog and moves focus to Close on open", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^filters$/i }));
    expect(screen.getByRole("dialog", { name: /map filters/i })).toBeInTheDocument();
    // Focus moves into the drawer (onto Close) so keyboard users aren't stranded.
    expect(screen.getByRole("button", { name: /close filters/i })).toHaveFocus();
  });

  it("passes shouldFitBounds=true when initialBbox is null", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    expect(MapLeafletMod.MapLeaflet).toHaveBeenCalledWith(
      expect.objectContaining({ shouldFitBounds: true }),
      // React calls function components with (props, ref) where ref is undefined
      // unless forwardRef is used.
      undefined,
    );
  });

  it("passes shouldFitBounds=false when initialBbox is supplied", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={[-80, 37, -77, 39]}
        initialZoom={12}
      />,
    );
    expect(MapLeafletMod.MapLeaflet).toHaveBeenCalledWith(
      expect.objectContaining({ shouldFitBounds: false, initialZoom: 12 }),
      undefined,
    );
  });

  it("passes the initial zoom through to the leaflet map", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={11}
      />,
    );
    expect(MapLeafletMod.MapLeaflet).toHaveBeenCalledWith(
      expect.objectContaining({ initialZoom: 11 }),
      undefined,
    );
  });

  it("renders a mobile filter trigger button", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    expect(screen.getByRole("button", { name: /open filters/i })).toBeInTheDocument();
  });

  it("opens the mobile sheet when the filter trigger is clicked", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /open filters/i }));
    // After opening the Sheet, FilterSidebar renders twice (desktop hidden via
    // CSS, mobile visible inside the Sheet). At minimum the heading count >= 1.
    const headings = screen.getAllByRole("heading", { name: /cold case map/i });
    expect(headings.length).toBeGreaterThanOrEqual(1);
  });

  it("shows the empty overlay when no cases are in view", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    expect(screen.getByText(/no cases in this view/i)).toBeInTheDocument();
  });

  it("does not show the empty overlay when cases are present", () => {
    renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    expect(screen.queryByText(/no cases in this view/i)).not.toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = renderWithNuqs(
      <ClientMap
        initialData={[sampleCase]}
        initialMode="points"
        initialClusters={[]}
        filterOptions={filterOptionsSample}
        facetCounts={null}
        totalAll={508}
        initialBbox={null}
        initialZoom={7}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
