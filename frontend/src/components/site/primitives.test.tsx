import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StatRail } from "./primitives";

describe("site primitives — StatRail", () => {
  it("renders static display text verbatim (no CountUp)", () => {
    render(<StatRail items={[{ display: "1961–2023", label: "Span" }]} />);
    expect(screen.getByText("1961–2023")).toBeInTheDocument();
    expect(screen.getByText("Span")).toBeInTheDocument();
  });
  it("renders a counted value when given `to`", () => {
    render(<StatRail items={[{ to: 11, label: "States" }]} />);
    expect(screen.getByText(/11/)).toBeInTheDocument();
    expect(screen.getByText("States")).toBeInTheDocument();
  });
});
