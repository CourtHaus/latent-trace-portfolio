import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

vi.mock("@/lib/getFilterOptions", () => ({
  getFilterOptionsOrNull: vi.fn(),
}));

import { SiteFooter } from "./SiteFooter";
import { getFilterOptionsOrNull } from "@/lib/getFilterOptions";

const mockResponse = {
  case_types: ["homicide"],
  cities: ["Richmond"],
  genders: ["female"],
  races: ["white"],
  states: ["VA", "TN"],
  weapons: ["firearm"],
  location_types: ["residence"],
  source_systems: [{ code: "VSPCCD_VA", name: "Virginia State Police Cold Case Database" }],
  year_range: { min: 1961, max: 2023 },
  dataset: { version: "v2026.04", last_ingested: "2026-04-20T10:00:00Z" },
};

describe("SiteFooter", () => {
  beforeEach(() => {
    vi.mocked(getFilterOptionsOrNull).mockReset();
    vi.mocked(getFilterOptionsOrNull).mockResolvedValue(mockResponse);
  });

  it("renders brand + a collapsed data-source summary linking to coverage", async () => {
    const tree = await SiteFooter();
    const { container } = render(tree);
    expect(screen.getByText("Latent Trace")).toBeInTheDocument();
    expect(container.textContent).toMatch(/Aggregated from 1 official law-enforcement source\b/);
    expect(screen.getByRole("link", { name: /see coverage/i })).toHaveAttribute(
      "href",
      "/methodology#data-sources",
    );
    // the footer no longer enumerates every source
    expect(
      screen.queryByText("Virginia State Police Cold Case Database"),
    ).not.toBeInTheDocument();
  });

  it("renders dataset version + copyright", async () => {
    const tree = await SiteFooter();
    render(tree);
    expect(screen.getByText(/DATASET v2026\.04/)).toBeInTheDocument();
    expect(screen.getByText(/©/)).toBeInTheDocument();
  });

  it("renders footer nav links including Privacy between Methodology and Contact", async () => {
    const tree = await SiteFooter();
    render(tree);
    const methodologyLink = screen.getByRole("link", { name: "Methodology" });
    const privacyLink = screen.getByRole("link", { name: "Privacy" });
    const contactLink = screen.getByRole("link", { name: "Contact" });
    expect(methodologyLink).toHaveAttribute("href", "/methodology");
    expect(privacyLink).toHaveAttribute("href", "/privacy");
    expect(contactLink).toHaveAttribute("href", "mailto:courtney@latenttrace.org");
    // Verify DOM order: Methodology before Privacy before Contact
    const allLinks = screen.getAllByRole("link");
    const idxM = allLinks.indexOf(methodologyLink);
    const idxP = allLinks.indexOf(privacyLink);
    const idxC = allLinks.indexOf(contactLink);
    expect(idxM).toBeLessThan(idxP);
    expect(idxP).toBeLessThan(idxC);
  });

  it("has no a11y violations", async () => {
    const tree = await SiteFooter();
    const { container } = render(tree);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders with empty sources + placeholder when the API is unreachable", async () => {
    vi.mocked(getFilterOptionsOrNull).mockResolvedValue(null);
    const tree = await SiteFooter();
    render(tree);
    expect(screen.getByText("Latent Trace")).toBeInTheDocument();
    expect(screen.getByText(/DATASET n\/a/)).toBeInTheDocument();
    expect(screen.queryByText(/VSPCCD/)).not.toBeInTheDocument();
  });
});
