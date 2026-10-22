import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { CaseHero } from "./CaseHero";

const base = {
  source_case_id: "2022-0003209",
  victim_primary_name: "Jane Doe",
  case_type: "homicide",
  incident_date: "1998-05-14",
  city: "Richmond",
  state: "VA",
  latitude: "37.5407",
  longitude: "-77.4360",
  daysOpen: 10000,
};

describe("CaseHero", () => {
  it("renders victim_primary_name as h1", () => {
    render(<CaseHero {...base} />);
    expect(screen.getByRole("heading", { level: 1, name: "Jane Doe" })).toBeInTheDocument();
  });

  it("shows id, humanized type, and source provenance in the eyebrow", () => {
    render(<CaseHero {...base} />);
    expect(screen.getByText(/#2022-0003209/)).toBeInTheDocument();
    expect(screen.getByText("Homicide")).toBeInTheDocument();
    expect(screen.getByText("Source record")).toBeInTheDocument();
  });

  it("shows the extraction tier in the eyebrow when present", () => {
    render(<CaseHero {...base} extractionTier={2} />);
    expect(screen.getByText("Tier-2 extracted")).toBeInTheDocument();
    expect(screen.queryByText("Source record")).not.toBeInTheDocument();
  });

  it("renders date + location + coordinates + days open in the specs", () => {
    render(<CaseHero {...base} />);
    expect(screen.getByText(/May 14, 1998/)).toBeInTheDocument();
    expect(screen.getByText(/Richmond, VA/)).toBeInTheDocument();
    expect(screen.getByText(/37\.5407, -77\.4360/)).toBeInTheDocument();
    expect(screen.getByText("10,000")).toBeInTheDocument();
  });

  it("handles null incident_date + null city gracefully", () => {
    render(<CaseHero {...base} incident_date={null} city={null} />);
    expect(screen.getByRole("heading", { level: 1, name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText(/VA/)).toBeInTheDocument();
    expect(screen.queryByText(/,\s*VA/)).not.toBeInTheDocument();
  });

  it("shows 'Unidentified' when victim_primary_name is null", () => {
    render(<CaseHero {...base} victim_primary_name={null} />);
    expect(screen.getByRole("heading", { level: 1, name: /unidentified/i })).toBeInTheDocument();
  });

  it("renders extracted suffix when incident_date_source is tier2", () => {
    render(<CaseHero {...base} incident_date_source="tier2" />);
    expect(screen.getByText(/\(extracted\)/i)).toBeInTheDocument();
  });

  it("no suffix when incident_date_source is source", () => {
    render(<CaseHero {...base} incident_date_source="source" />);
    expect(screen.queryByText(/\(extracted\)/i)).not.toBeInTheDocument();
  });

  it("no suffix when incident_date_source is omitted", () => {
    render(<CaseHero {...base} />);
    expect(screen.queryByText(/\(extracted\)/i)).not.toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(<CaseHero {...base} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
