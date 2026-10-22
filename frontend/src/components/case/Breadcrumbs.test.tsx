import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { Breadcrumbs } from "./Breadcrumbs";

describe("Breadcrumbs", () => {
  it("renders each item, with non-terminal items as links", () => {
    render(
      <Breadcrumbs items={[
        { label: "Home", href: "/" },
        { label: "Cold Cases", href: "/cold-cases" },
        { label: "Jane Doe" },
      ]} />,
    );
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Cold Cases" })).toHaveAttribute("href", "/cold-cases");
    // Terminal item is rendered but not a link.
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Jane Doe" })).not.toBeInTheDocument();
  });

  it("renders as a <nav> with aria-label=Breadcrumb", () => {
    render(<Breadcrumbs items={[{ label: "Home", href: "/" }, { label: "End" }]} />);
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(
      <Breadcrumbs items={[{ label: "Home", href: "/" }, { label: "End" }]} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
