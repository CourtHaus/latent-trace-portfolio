import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { CorrelationBars, type CorrelationItem } from "./CorrelationBars";

const item: CorrelationItem = {
  case_id: 7, slug: "x", victim_primary_name: "Thomas Henderson", city: "Henrico", state: "VA",
  year: 2007, score: 7.2, score_max: 10, proximity_factor: 0.62, distance_miles: 14.8, years_apart: 9,
  matched_dimensions: [
    { name: "weapon", value: "firearm", low_confidence: false, weight: 6.0 },
    { name: "victim_gender", value: "F", low_confidence: false, weight: 1.5 },
  ],
};

describe("CorrelationBars", () => {
  it("renders a linked row per lead with score + context", () => {
    render(<CorrelationBars items={[item]} fromCaseId={1} />);
    const link = screen.getByRole("link", { name: /Thomas Henderson/ });
    expect(link).toHaveAttribute("href", "/cold-cases/7/x");
    expect(screen.getByText("7.2")).toBeInTheDocument();
    expect(screen.getByText(/Henrico, VA · 2007 · 15mi · 9yr/)).toBeInTheDocument();
  });
  it("renders a proximity line with the discount factor and raw distance/years", () => {
    render(<CorrelationBars items={[item]} fromCaseId={1} />);
    expect(screen.getByText(/proximity x0\.62 at 15 mi \/ 9 yr/)).toBeInTheDocument();
  });
  it("draws a segment per matched dimension sized by weight/score_max", () => {
    const { container } = render(<CorrelationBars items={[item]} fromCaseId={1} />);
    const segs = container.querySelectorAll("[data-seg]");
    expect(segs.length).toBe(2);
    expect((segs[0] as HTMLElement).style.width).toBe(`${(6.0 / 10) * 100}%`);
    expect((segs[1] as HTMLElement).style.width).toBe(`${(1.5 / 10) * 100}%`);
  });
  it("renders the dimension legend", () => {
    render(<CorrelationBars items={[item]} fromCaseId={1} />);
    expect(screen.getByText(/weapon/i)).toBeInTheDocument();
  });
  it("marks a low-confidence MO segment uncertain but never a demographic", () => {
    const it2: CorrelationItem = {
      ...item,
      matched_dimensions: [
        { name: "weapon", value: "firearm", low_confidence: true, weight: 1.0 },
        { name: "victim_gender", value: "F", low_confidence: true, weight: 0.5 },
      ],
    };
    const { container } = render(<CorrelationBars items={[it2]} fromCaseId={1} />);
    const weapon = container.querySelector('[data-seg="weapon"]') as HTMLElement;
    const gender = container.querySelector('[data-seg="victim_gender"]') as HTMLElement;
    expect(weapon.getAttribute("title")).toMatch(/uncertain/);
    expect(gender.getAttribute("title")).not.toMatch(/uncertain/); // demographics never "uncertain"
    const bar = container.querySelector('[role="img"]') as HTMLElement;
    expect(bar.getAttribute("aria-label")).toMatch(/Weapon: firearm \(uncertain\)/);
    expect(bar.getAttribute("aria-label")).toMatch(/Gender: F(,|$)/);
  });
});
