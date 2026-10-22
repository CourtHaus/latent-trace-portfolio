import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import TermsPage from "./page";

describe("TermsPage", () => {
  it("renders the Terms heading", () => {
    render(<TermsPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /terms of use/i }),
    ).toBeInTheDocument();
  });

  it("has a corrections and removals section", () => {
    render(<TermsPage />);
    expect(
      screen.getByRole("heading", { name: /corrections and removals/i }),
    ).toBeInTheDocument();
  });

  it("states the load-bearing protections", () => {
    render(<TermsPage />);
    // leads, not conclusions
    expect(screen.getByText(/leads for human review/i)).toBeInTheDocument();
    // not a consumer report (no FCRA-style use)
    expect(screen.getByText(/not a consumer report/i)).toBeInTheDocument();
    // not an official record
    expect(screen.getByText(/not an official record/i)).toBeInTheDocument();
    // race is never inferred
    expect(screen.getByText(/race is\s+never inferred/i)).toBeInTheDocument();
  });

  it("surfaces a mailto contact link and cross-links to Privacy", () => {
    render(<TermsPage />);
    const contacts = screen.getAllByRole("link", {
      name: "courtney@latenttrace.org",
    });
    expect(contacts.length).toBeGreaterThan(0);
    for (const c of contacts) {
      expect(c).toHaveAttribute("href", "mailto:courtney@latenttrace.org");
    }
    expect(screen.getByRole("link", { name: "Privacy" })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });

  it("contains no em-dash in the rendered copy (house style)", () => {
    const { container } = render(<TermsPage />);
    expect(container.textContent).not.toContain("—");
  });

  it("has no a11y violations", async () => {
    const { container } = render(<TermsPage />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
