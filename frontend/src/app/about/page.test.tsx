import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import AboutPage from "./page";

describe("AboutPage", () => {
  it("renders the founder's-note headline and author attribution", () => {
    render(<AboutPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /why this exists/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Courtney Hammond/)).toBeInTheDocument();
  });

  it("surfaces a mailto contact link", () => {
    render(<AboutPage />);
    const contact = screen.getByRole("link", {
      name: "courtney@latenttrace.org",
    });
    expect(contact).toHaveAttribute("href", "mailto:courtney@latenttrace.org");
  });

  it("cross-links to the methodology page for the how", () => {
    render(<AboutPage />);
    expect(
      screen.getByRole("link", { name: "Methodology" }),
    ).toHaveAttribute("href", "/methodology");
  });

  it("states the load-bearing ethical commitments", () => {
    render(<AboutPage />);
    // leads for review, never an accusation
    expect(screen.getByText(/never an accusation/)).toBeInTheDocument();
    // race is never inferred
    expect(screen.getByText(/never permitted to infer a victim's race/)).toBeInTheDocument();
    // Local narrative extraction is distinguished from external service data flows
    expect(screen.getByText(/Narrative extraction uses a locally hosted model/)).toBeInTheDocument();
    expect(screen.getByText(/Hosting, geocoding, and optional source tooling use separate services/)).toBeInTheDocument();
    expect(screen.queryByText(/no case data is handed to an outside company/)).not.toBeInTheDocument();
    // primary-source-only standard
    expect(screen.getByText(/The primary record, or nothing/)).toBeInTheDocument();
  });

  it("contains no em-dash in the rendered copy (house style)", () => {
    const { container } = render(<AboutPage />);
    expect(container.textContent).not.toContain("—");
  });

  it("has no a11y violations", async () => {
    const { container } = render(<AboutPage />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
