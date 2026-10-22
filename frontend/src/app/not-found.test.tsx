import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import NotFound from "./not-found";

describe("NotFound (404)", () => {
  it("renders the not-found heading", () => {
    render(<NotFound />);
    expect(
      screen.getByRole("heading", { level: 1, name: /page not found/i }),
    ).toBeInTheDocument();
  });

  it("links to the register and home", () => {
    render(<NotFound />);
    expect(screen.getByRole("link", { name: /browse cases/i })).toHaveAttribute(
      "href",
      "/cold-cases",
    );
    expect(screen.getByRole("link", { name: /home/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("has no a11y violations", async () => {
    const { container } = render(<NotFound />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
