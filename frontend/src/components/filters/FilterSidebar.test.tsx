import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { axe } from "vitest-axe";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { FilterSidebar } from "./FilterSidebar";

const trackMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/analytics/client", () => ({ track: trackMock }));

const baseProps = {
  title: "Test Title",
  isPending: false,
  caseTypeOptions: ["homicide"],
  cityOptions: ["Richmond"],
  victimGenderOptions: ["Female"],
  victimRaceOptions: ["White"],
  weaponOptions: ["firearm", "knife"],
  locationTypeOptions: ["residence", "public_outdoor"],
  sourceSystemOptions: [
    { code: "VSPCCD_VA", name: "Virginia State Police Cold Case DB" },
  ],
  yearMin: null,
  yearMax: null,
  caseType: [],
  city: null,
  victimGender: [],
  victimRace: [],
  weapon: [],
  locationType: [],
  sourceSystem: [],
  precision: [],
  onYearRangeChange: vi.fn(),
  onCaseTypeChange: vi.fn(),
  onCityChange: vi.fn(),
  onVictimGenderChange: vi.fn(),
  onVictimRaceChange: vi.fn(),
  onWeaponChange: vi.fn(),
  onLocationTypeChange: vi.fn(),
  onSourceSystemChange: vi.fn(),
  onPrecisionChange: vi.fn(),
  onResetFilters: vi.fn(),
};

function renderSidebar(overrides: Partial<React.ComponentProps<typeof FilterSidebar>> = {}) {
  return render(
    <NuqsTestingAdapter>
      <FilterSidebar {...baseProps} {...overrides} />
    </NuqsTestingAdapter>,
  );
}

describe("FilterSidebar — props-driven", () => {
  it("labels the sidebar region with the title prop", () => {
    renderSidebar({ title: "Cold Cases" });
    expect(screen.getByRole("complementary", { name: "Cold Cases" })).toBeInTheDocument();
  });

  it("renders the FILTERS header with a Clear all action", () => {
    renderSidebar();
    expect(screen.getByText("Filters")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear all/i })).toBeInTheDocument();
  });

  it("renders headerActions content when provided", () => {
    renderSidebar({ headerActions: <button>Recenter</button> });
    expect(screen.getByRole("button", { name: /recenter/i })).toBeInTheDocument();
  });

  it("does NOT render map-specific Recenter when headerActions is not provided", () => {
    renderSidebar();
    expect(screen.queryByRole("button", { name: /recenter/i })).toBeNull();
  });

  it("renders footerSlot content when provided", () => {
    renderSidebar({ footerSlot: <span data-testid="dataset-footer">508 cases</span> });
    expect(screen.getByTestId("dataset-footer")).toBeInTheDocument();
  });

  it("does NOT render a footer region when footerSlot is not provided", () => {
    const { container } = renderSidebar();
    expect(container.querySelector("footer")).toBeNull();
  });

  it("has no a11y violations with both slots populated", async () => {
    const { container } = renderSidebar({
      title: "Cold Cases",
      headerActions: <button>Recenter</button>,
      footerSlot: <span>508 cases total</span>,
    });
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("FilterSidebar — C1.5 sectioning", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders five section headers in the locked order", () => {
    const { container } = renderSidebar();
    const headers = Array.from(
      container.querySelectorAll('[aria-controls^="section-body-"]'),
    );
    expect(headers.map((h) => h.textContent?.trim())).toEqual([
      "Data source",
      "Case attributes",
      "Victim",
      "Modus operandi",
      "Geocoding precision",
    ]);
  });

  it("renders facet counts beside options when counts are provided", () => {
    renderSidebar({
      counts: {
        caseType: { homicide: 42 },
        gender: {},
        race: {},
        weapon: { firearm: 7 },
        locationType: {},
        sourceSystem: { VSPCCD_VA: 99 },
        precision: {},
      },
    });
    expect(screen.getByText("42")).toBeInTheDocument(); // case type
    expect(screen.getByText("7")).toBeInTheDocument(); // weapon
    // Data source starts collapsed by default — expand to reach its counts.
    fireEvent.click(screen.getByRole("button", { name: /data source/i }));
    expect(screen.getByText("99")).toBeInTheDocument(); // source system
  });

  it("renders Weapon and Location type checkboxes inside the MO section", () => {
    renderSidebar();
    expect(screen.getByText("Weapon")).toBeInTheDocument();
    expect(screen.getByText("Location type")).toBeInTheDocument();
    expect(screen.getByLabelText("firearm")).toBeInTheDocument();
    expect(screen.getByLabelText("residence")).toBeInTheDocument();
  });

  it("includes the methodology link in the MO section header", () => {
    renderSidebar();
    const link = screen.getByRole("link", { name: /about these fields/i });
    expect(link).toHaveAttribute("href", "/methodology#modus-operandi");
  });

  it("toggles section collapse when the section header is clicked", () => {
    renderSidebar();
    // MO header is the third h3 in the sidebar
    const moHeader = screen.getByRole("button", { name: /modus operandi/i });
    fireEvent.click(moHeader);
    expect(screen.queryByLabelText("firearm")).not.toBeInTheDocument();
    fireEvent.click(moHeader);
    expect(screen.getByLabelText("firearm")).toBeInTheDocument();
  });

  it("renders the source section with options using name as label and code as value", () => {
    renderSidebar();
    // The "Data source" section header
    const sourceHeader = screen.getByRole("button", { name: /data source/i });
    expect(sourceHeader).toBeInTheDocument();
    // Data source starts collapsed by default — expand to reveal its options.
    fireEvent.click(sourceHeader);
    // The checkbox is labeled with the option name
    expect(screen.getByLabelText("Virginia State Police Cold Case DB")).toBeInTheDocument();
  });

  it("calls onSourceSystemChange with the toggled code when a source checkbox changes", () => {
    const onSourceSystemChange = vi.fn();
    renderSidebar({ onSourceSystemChange });
    fireEvent.click(screen.getByRole("button", { name: /data source/i }));
    fireEvent.click(screen.getByLabelText("Virginia State Police Cold Case DB"));
    expect(onSourceSystemChange).toHaveBeenCalledWith(["VSPCCD_VA"]);
  });

  it("marks a source checkbox checked when its code is in sourceSystem", () => {
    renderSidebar({ sourceSystem: ["VSPCCD_VA"] });
    fireEvent.click(screen.getByRole("button", { name: /data source/i }));
    const checkbox = screen.getByLabelText("Virginia State Police Cold Case DB") as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });

  it("renders precision checkboxes for all four geocoding levels", () => {
    renderSidebar({ precision: [] });
    expect(screen.getByLabelText("street")).toBeInTheDocument();
    expect(screen.getByLabelText("landmark")).toBeInTheDocument();
    expect(screen.getByLabelText("zip")).toBeInTheDocument();
    expect(screen.getByLabelText("county")).toBeInTheDocument();
  });

  it("calls onPrecisionChange with toggled value when a precision checkbox changes", () => {
    const onPrecisionChange = vi.fn();
    renderSidebar({ onPrecisionChange });
    fireEvent.click(screen.getByLabelText("street"));
    expect(onPrecisionChange).toHaveBeenCalledWith(["street"]);
  });

  it("marks a precision checkbox checked when its value is in precision", () => {
    renderSidebar({ precision: ["zip"] });
    const checkbox = screen.getByLabelText("zip") as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });
});

describe("FilterSidebar — telemetry", () => {
  beforeEach(() => {
    localStorage.clear();
    trackMock.mockClear();
  });

  it("emits filter_applied with only the filter_key when a weapon checkbox changes", () => {
    const onWeaponChange = vi.fn();
    renderSidebar({ onWeaponChange });
    fireEvent.click(screen.getByLabelText("firearm"));
    expect(trackMock).toHaveBeenCalledWith("filter_applied", { filter_key: "weapon" });
    // Privacy: no call should contain the filter value ("firearm")
    const leak = trackMock.mock.calls.some(([, props]) =>
      props && JSON.stringify(props).includes("firearm"),
    );
    expect(leak).toBe(false);
  });

  it("emits filter_cleared scope=all when the Clear all button is clicked", () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(trackMock).toHaveBeenCalledWith("filter_cleared", { scope: "all" });
  });
});
