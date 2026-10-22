import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AppliedFilterChips, type AppliedFilters } from "./AppliedFilterChips";

const trackMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/analytics/client", () => ({ track: trackMock }));

const empty: AppliedFilters = {
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
};

describe("AppliedFilterChips", () => {
  it("renders nothing when no filters are active", () => {
    const { container } = render(
      <AppliedFilterChips
        filters={empty}
        onClearDimension={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders a range chip as 'Year: lo–hi'", () => {
    render(
      <AppliedFilterChips
        filters={{ ...empty, yearMin: 1980, yearMax: 1990 }}
        onClearDimension={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(screen.getByText(/1980–1990/)).toBeInTheDocument();
  });

  it("renders a single-value chip as 'Field: value'", () => {
    render(
      <AppliedFilterChips
        filters={{ ...empty, city: "Richmond" }}
        onClearDimension={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(screen.getByText(/Richmond/)).toBeInTheDocument();
  });

  it("renders a multi-value chip with comma-collapse", () => {
    render(
      <AppliedFilterChips
        filters={{ ...empty, weapon: ["firearm", "knife"] }}
        onClearDimension={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(screen.getByText(/firearm, knife/)).toBeInTheDocument();
  });

  it("truncates multi-value chips at 3 with '+N more'", () => {
    render(
      <AppliedFilterChips
        filters={{ ...empty, weapon: ["firearm", "knife", "blunt", "personal", "fire"] }}
        onClearDimension={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(screen.getByText(/firearm, knife, blunt \+2 more/)).toBeInTheDocument();
  });

  it("clear button on a chip dispatches onClearDimension with the dimension key", () => {
    const onClear = vi.fn();
    render(
      <AppliedFilterChips
        filters={{ ...empty, weapon: ["firearm"] }}
        onClearDimension={onClear}
        onClearAll={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText(/clear weapon filter/i));
    expect(onClear).toHaveBeenCalledWith("weapon");
  });

  it("'Clear all' button dispatches onClearAll", () => {
    const onClearAll = vi.fn();
    render(
      <AppliedFilterChips
        filters={{ ...empty, weapon: ["firearm"], city: "Richmond" }}
        onClearDimension={() => {}}
        onClearAll={onClearAll}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(onClearAll).toHaveBeenCalled();
  });
});

describe("AppliedFilterChips — telemetry", () => {
  beforeEach(() => {
    trackMock.mockClear();
  });

  it("emits filter_cleared scope=single when a chip X button is clicked", () => {
    render(
      <AppliedFilterChips
        filters={{ ...empty, weapon: ["firearm"] }}
        onClearDimension={() => {}}
        onClearAll={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText(/clear weapon filter/i));
    expect(trackMock).toHaveBeenCalledWith("filter_cleared", { scope: "single" });
  });

  it("emits filter_cleared scope=all when 'Clear all' is clicked", () => {
    render(
      <AppliedFilterChips
        filters={{ ...empty, weapon: ["firearm"], city: "Richmond" }}
        onClearDimension={() => {}}
        onClearAll={() => {}}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(trackMock).toHaveBeenCalledWith("filter_cleared", { scope: "all" });
  });
});
