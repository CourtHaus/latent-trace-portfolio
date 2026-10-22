import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Provenance } from "./Provenance";
import type { SourceSummaryItem } from "@/lib/getSourcesSummary";

const mockSource: SourceSummaryItem = {
  code: "OH-AG",
  name: "Ohio Attorney General",
  state: "Ohio",
  case_count: 2796,
  geocoded_count: 2700,
  year_min: 1960,
  year_max: 2023,
};

describe("Provenance", () => {
  it("renders a row per source with formatted counts and no em-dash", () => {
    const { container } = render(<Provenance sources={[mockSource]} />);

    // source code renders
    expect(screen.getByText("OH-AG")).toBeTruthy();

    // jurisdiction renders
    expect(screen.getByText("Ohio")).toBeTruthy();

    // 4-digit count with comma (2,796)
    expect(screen.getByText("2,796")).toBeTruthy();

    // no em-dash anywhere in rendered output
    expect(container.textContent).not.toContain("—");
  });
});
