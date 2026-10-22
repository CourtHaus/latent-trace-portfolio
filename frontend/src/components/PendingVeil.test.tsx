import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { PendingVeil } from "./PendingVeil";

describe("PendingVeil", () => {
  it("always renders children", () => {
    render(
      <PendingVeil isPending={false}>
        <p>content</p>
      </PendingVeil>,
    );
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("is not busy and shows no badge when idle", () => {
    const { container } = render(
      <PendingVeil isPending={false}>
        <p>content</p>
      </PendingVeil>,
    );
    expect(container.querySelector('[aria-busy="true"]')).toBeNull();
    expect(screen.queryByText(/updating/i)).not.toBeInTheDocument();
  });

  it("marks busy and shows the Updating badge while pending", () => {
    render(
      <PendingVeil isPending>
        <p>content</p>
      </PendingVeil>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/updating/i);
    expect(screen.getByText("content").closest('[aria-busy="true"]')).not.toBeNull();
  });

  it("dims + blocks interaction by default while pending", () => {
    const { container } = render(
      <PendingVeil isPending>
        <p>content</p>
      </PendingVeil>,
    );
    const wrapper = container.querySelector('[aria-busy="true"]');
    expect(wrapper?.className).toContain("opacity-60");
    expect(wrapper?.className).toContain("pointer-events-none");
  });

  it("does not dim when dim={false}, but still badges", () => {
    const { container } = render(
      <PendingVeil isPending dim={false}>
        <p>content</p>
      </PendingVeil>,
    );
    const wrapper = container.querySelector('[aria-busy="true"]');
    expect(wrapper?.className).not.toContain("opacity-60");
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("has no a11y violations in either state", async () => {
    const idle = render(
      <PendingVeil isPending={false}>
        <p>content</p>
      </PendingVeil>,
    );
    expect(await axe(idle.container)).toHaveNoViolations();
    idle.unmount();

    const busy = render(
      <PendingVeil isPending>
        <p>content</p>
      </PendingVeil>,
    );
    expect(await axe(busy.container)).toHaveNoViolations();
  });
});
