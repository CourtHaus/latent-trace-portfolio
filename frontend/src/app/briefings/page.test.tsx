import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import BriefingsPage from "./page";

describe("BriefingsPage", () => {
  it("renders the headline and an in-development status", () => {
    render(<BriefingsPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /ask the corpus/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/in development/i)).toBeInTheDocument();
  });

  it("makes clear it is not yet available", () => {
    render(<BriefingsPage />);
    expect(screen.getByText(/isn't live yet/i)).toBeInTheDocument();
  });

  it("keeps the load-bearing framing (leads not accusations, local)", () => {
    render(<BriefingsPage />);
    expect(screen.getByText(/never an accusation/)).toBeInTheDocument();
    expect(screen.getByText(/local hardware/)).toBeInTheDocument();
  });

  it("cross-links to the existing surfaces", () => {
    render(<BriefingsPage />);
    expect(screen.getByRole("link", { name: "Cases" })).toHaveAttribute("href", "/cold-cases");
    expect(screen.getByRole("link", { name: "Map" })).toHaveAttribute("href", "/cold-cases/map");
    expect(
      screen.getAllByRole("link", { name: "Methodology" })[0],
    ).toHaveAttribute("href", "/methodology");
  });

  it("contains no em-dash in the rendered copy (house style)", () => {
    const { container } = render(<BriefingsPage />);
    expect(container.textContent).not.toContain("—");
  });

  it("has no a11y violations", async () => {
    const { container } = render(<BriefingsPage />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
