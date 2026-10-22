import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { MarkerPopup } from "./MarkerPopup";

const sampleCase = {
  case_id: 42,
  slug: "jane-doe-richmond-va-1998",
  source_case_id: "2022-0003209",
  case_name: "Augusta County - Case: 2022-0003209 - Jane Doe",
  case_type: "homicide",
  incident_date: "1998-05-14",
  latitude: 37.5407,
  longitude: -77.4360,
  state: "VA",
  city: "Richmond",
  victim_primary_name: "Jane Doe",
  victim_genders: ["Female"],
  victim_races: ["White"],
  geocode_precision: null,
};

describe("MarkerPopup", () => {
  it("renders victim_primary_name as h3 (not case_name blob)", () => {
    render(<MarkerPopup case={sampleCase} />);
    expect(screen.getByRole("heading", { level: 3, name: "Jane Doe" })).toBeInTheDocument();
    // The full blob should NOT appear
    expect(screen.queryByText(/Augusta County - Case/)).not.toBeInTheDocument();
  });

  it("shows source_case_id in the popup header", () => {
    render(<MarkerPopup case={sampleCase} />);
    expect(screen.getByText(/#2022-0003209/)).toBeInTheDocument();
  });

  it("renders case type, date, and location", () => {
    render(<MarkerPopup case={sampleCase} />);
    expect(screen.getByText(/homicide/i)).toBeInTheDocument();
    expect(screen.getByText(/May 14, 1998/)).toBeInTheDocument();
    expect(screen.getByText(/Richmond, VA/)).toBeInTheDocument();
  });

  it("renders 'View case →' link pointing at the canonical URL", () => {
    render(<MarkerPopup case={sampleCase} />);
    const link = screen.getByRole("link", { name: /view case/i });
    expect(link).toHaveAttribute("href", "/cold-cases/42/jane-doe-richmond-va-1998");
  });

  it("shows 'Unidentified' when victim_primary_name is null", () => {
    const unidentifiedCase = { ...sampleCase, victim_primary_name: null };
    render(<MarkerPopup case={unidentifiedCase} />);
    expect(screen.getByRole("heading", { level: 3, name: /unidentified/i })).toBeInTheDocument();
  });

  it("gracefully handles null incident_date + null city", () => {
    const sparseCase = { ...sampleCase, incident_date: null, city: null };
    render(<MarkerPopup case={sparseCase} />);
    expect(screen.getByRole("heading", { level: 3, name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText("VA")).toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(<MarkerPopup case={sampleCase} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
