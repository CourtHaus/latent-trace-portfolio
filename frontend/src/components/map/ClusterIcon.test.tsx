import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { ClusterIcon, clusterTierSize } from "./ClusterIcon";

describe("ClusterIcon", () => {
  it("renders the count", () => {
    render(<ClusterIcon count={42} />);
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("assigns a size class tier based on count", () => {
    const { container: small } = render(<ClusterIcon count={5} />);
    const { container: medium } = render(<ClusterIcon count={50} />);
    const { container: large } = render(<ClusterIcon count={200} />);
    expect(small.innerHTML).not.toEqual(medium.innerHTML);
    expect(medium.innerHTML).not.toEqual(large.innerHTML);
  });

  it("clusterTierSize returns tier-appropriate pixel sizes", () => {
    expect(clusterTierSize(5)).toBe(30);
    expect(clusterTierSize(50)).toBe(40);
    expect(clusterTierSize(200)).toBe(50);
  });

  it("renders as an outline ring with a dark interior (not a bright fill)", () => {
    const { container } = render(<ClusterIcon count={12} />);
    const bubble = container.firstChild as HTMLElement;
    expect(bubble.className).toContain("border-primary");
    expect(bubble.className).toContain("bg-background/55");
    expect(bubble.className).toContain("text-primary");
    expect(bubble.className).not.toContain("bg-primary/20");
  });

  it("has no a11y violations", async () => {
    const { container } = render(<ClusterIcon count={10} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
