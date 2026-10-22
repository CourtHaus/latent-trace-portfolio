import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { SectionHeader, OutlineButton, StatRail } from "./primitives";

describe("landing primitives", () => {
  it("SectionHeader renders index, heading, and links the aria id", () => {
    render(<SectionHeader idx="02" id="d2" title="The shape of a century" desc="x" />);
    const h = screen.getByRole("heading", { name: "The shape of a century" });
    expect(h).toHaveAttribute("id", "d2");
    expect(screen.getByText("02")).toBeInTheDocument();
  });
  it("OutlineButton renders an anchor with no arrow glyph", () => {
    render(<OutlineButton href="/x">Open the index</OutlineButton>);
    const a = screen.getByRole("link", { name: "Open the index" });
    expect(a.textContent).not.toMatch(/[→➔➝]/);
  });
  it("StatRail renders count and label", () => {
    render(<StatRail items={[{ to: 15, label: "Jurisdictions" }]} />);
    expect(screen.getByText("Jurisdictions")).toBeInTheDocument();
    expect(screen.getByText(/15/)).toBeInTheDocument();
  });
});
