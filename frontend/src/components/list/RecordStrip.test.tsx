import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RecordStrip } from "./RecordStrip";
import type { components } from "@/lib/api-types";

type Row = components["schemas"]["ColdCaseListItem"];

const base: Row = {
  case_id: 42, slug: "x", source_case_id: "CS-OH-2291", case_name: "n",
  case_type: "homicide", incident_date: "2004-03-01", city: "Cleveland", state: "OH",
  victim_primary_name: "Linda Carrasco", victim_primary_gender: "female",
  victim_primary_age: 34, victim_primary_race: "White",
  weapon: null, weapon_low_confidence: false, location_type: null,
  location_type_low_confidence: false, geocode_precision: "street",
};

describe("RecordStrip", () => {
  it("links to the case detail with an accessible label and shows identity", () => {
    render(<RecordStrip row={base} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/cold-cases/42/x");
    expect(link).toHaveAccessibleName(/Linda Carrasco/);
    expect(screen.getByText("Linda Carrasco")).toBeInTheDocument();
    expect(screen.getByText("2004")).toBeInTheDocument();
    expect(screen.getByText(/CS-OH-2291/)).toBeInTheDocument();
  });
  it("shows demographics and the geocoded state", () => {
    render(<RecordStrip row={base} />);
    expect(screen.getByText("Female")).toBeInTheDocument(); // humanized from "female"
    expect(screen.getByText("Age 34")).toBeInTheDocument();
    expect(screen.getByText("White")).toBeInTheDocument();
    expect(screen.getByText(/geocoded/)).toBeInTheDocument();
  });
  it("dims missing demographics to '<label> n/a' and shows no-coords", () => {
    render(<RecordStrip row={{ ...base, victim_primary_gender: null, victim_primary_age: null, victim_primary_race: null, geocode_precision: null }} />);
    expect(screen.getByText("Gender n/a")).toBeInTheDocument();
    expect(screen.getByText("Age n/a")).toBeInTheDocument();
    expect(screen.getByText("Race n/a")).toBeInTheDocument();
    expect(screen.getByText(/no coords/)).toBeInTheDocument();
  });
  it("falls back to 'Unidentified' when the victim name is null", () => {
    render(<RecordStrip row={{ ...base, victim_primary_name: null }} />);
    expect(screen.getByText("Unidentified")).toBeInTheDocument();
  });
});
