import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/cold-cases",
}));

import { ListClient } from "./ListClient";

const rows = [
  {
    case_id: 1,
    slug: "jane-doe",
    source_case_id: "2022-0003209",
    case_name: "Jane Doe",
    case_type: "homicide",
    incident_date: "1998-05-14",
    city: "Richmond",
    state: "VA",
    victim_primary_name: "Jane Doe",
    weapon: null,
    weapon_low_confidence: false,
    location_type: null,
    location_type_low_confidence: false,
    victim_primary_gender: null,
    victim_primary_age: null,
    victim_primary_race: null,
    geocode_precision: null,
  },
  {
    case_id: 2,
    slug: "john-roe",
    source_case_id: "2021-0001111",
    case_name: "John Roe",
    case_type: "homicide",
    incident_date: "2001-09-02",
    city: "Norfolk",
    state: "VA",
    victim_primary_name: "John Roe",
    weapon: "firearm",
    weapon_low_confidence: false,
    location_type: "residence",
    location_type_low_confidence: false,
    victim_primary_gender: "Male",
    victim_primary_age: 34,
    victim_primary_race: "White",
    geocode_precision: "street",
  },
];

const filterOptions = {
  case_types: ["homicide", "missing-person"],
  cities: ["Richmond", "Norfolk"],
  genders: ["Female", "Male"],
  races: ["White", "Black"],
  states: ["VA"],
  weapons: ["firearm", "knife"],
  location_types: ["residence", "public_outdoor"],
  source_systems: [{ code: "VSPCCD_VA", name: "Virginia State Police Cold Case Database" }],
  year_range: { min: 1958, max: 2023 },
  dataset: { version: "v0", last_ingested: "2026-04-21T00:00:00Z" },
};

function renderWithNuqs(
  ui: React.ReactElement,
  searchParams: Record<string, string> = {},
) {
  const query = new URLSearchParams(searchParams).toString();
  return render(ui, {
    wrapper: ({ children }) => (
      <NuqsTestingAdapter searchParams={`?${query}`}>{children}</NuqsTestingAdapter>
    ),
  });
}

describe("ListClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("labels the sidebar region 'Cold Cases'", () => {
    renderWithNuqs(
      <ListClient
        rows={rows}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={1}
        totalUnfiltered={508}
      />,
    );
    expect(screen.getByRole("complementary", { name: "Cold Cases" })).toBeInTheDocument();
  });

  it("renders one RecordStrip link per row", () => {
    renderWithNuqs(
      <ListClient
        rows={rows}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={2}
        totalUnfiltered={508}
      />,
    );
    // Match only record links (/cold-cases/<id>/<slug>), excluding the footer
    // "View on map" link (/cold-cases/map) — so this genuinely counts one per row.
    const caseLinks = screen
      .getAllByRole("link")
      .filter((a) => /^\/cold-cases\/\d+\//.test(a.getAttribute("href") ?? ""));
    expect(caseLinks).toHaveLength(2);
  });

  it("exposes the toolbar sort control", () => {
    renderWithNuqs(
      <ListClient
        rows={rows}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={2}
        totalUnfiltered={508}
      />,
    );
    expect(screen.getByLabelText(/sort cases/i)).toBeInTheDocument();
  });

  it("wraps the results in a pending-aware region (idle = not busy)", () => {
    const { container } = renderWithNuqs(
      <ListClient
        rows={rows}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={1}
        totalUnfiltered={508}
      />,
    );
    // PendingVeil renders aria-busy on the results wrapper; idle => "false".
    expect(container.querySelector('[aria-busy="false"]')).not.toBeNull();
  });

  it("renders empty state when totalFiltered is 0", () => {
    renderWithNuqs(
      <ListClient
        rows={[]}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={0}
        totalUnfiltered={508}
      />,
    );
    expect(screen.getByText(/no cases match these filters/i)).toBeInTheDocument();
    // Reset button in main content
    const resetButtons = screen.getAllByRole("button", { name: /reset filters/i });
    expect(resetButtons.length).toBeGreaterThanOrEqual(1);
  });

  it("sidebar footer shows dataset total", () => {
    renderWithNuqs(
      <ListClient
        rows={rows}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={1}
        totalUnfiltered={508}
      />,
    );
    expect(screen.getByText(/508 cases in the dataset/i)).toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = renderWithNuqs(
      <ListClient
        rows={rows}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={1}
        totalUnfiltered={508}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it("opens the mobile filter sheet when trigger is clicked", () => {
    renderWithNuqs(
      <ListClient
        rows={rows}
        filterOptions={filterOptions}
        facetCounts={null}
        totalFiltered={1}
        totalUnfiltered={508}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /open filters/i }));
    // Sheet open => its sr-only title renders, and a second filter region exists.
    expect(screen.getByText("Cold Cases Filters")).toBeInTheDocument();
  });
});
