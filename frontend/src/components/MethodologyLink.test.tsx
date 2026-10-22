import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MethodologyLink } from "./MethodologyLink";

describe("MethodologyLink", () => {
  it("renders an anchor pointing to /methodology with the correct fragment", () => {
    render(<MethodologyLink section="modus-operandi">About these fields</MethodologyLink>);
    const link = screen.getByRole("link", { name: /about these fields/i });
    expect(link).toHaveAttribute("href", "/methodology#modus-operandi");
  });

  it("supports any section anchor (single source of truth for href shape)", () => {
    render(<MethodologyLink section="data-sources">Data sources</MethodologyLink>);
    const link = screen.getByRole("link", { name: /data sources/i });
    expect(link).toHaveAttribute("href", "/methodology#data-sources");
  });
});
