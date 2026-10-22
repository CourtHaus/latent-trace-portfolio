import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import NotFound from "./not-found";

describe("MapNotFound", () => {
  it("shows map-specific copy", () => {
    render(<NotFound />);
    expect(screen.getByText(/couldn't load the map/i)).toBeInTheDocument();
  });

  it("links back to the list", () => {
    render(<NotFound />);
    const link = screen.getByRole("link", { name: /browse all cold cases/i });
    expect(link).toHaveAttribute("href", "/cold-cases");
  });

  it("has no a11y violations", async () => {
    const { container } = render(<NotFound />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
