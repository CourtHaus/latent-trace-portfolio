import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { MapLoadingFallback } from "./MapLoadingFallback";

describe("MapLoadingFallback", () => {
  it("renders an accessible loading status", () => {
    render(<MapLoadingFallback />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading map/i);
  });

  it("has no a11y violations", async () => {
    const { container } = render(<MapLoadingFallback />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
