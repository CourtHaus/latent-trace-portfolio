import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import { MapEmptyOverlay } from "./MapEmptyOverlay";

describe("MapEmptyOverlay", () => {
  it("shows the no-cases message", () => {
    render(<MapEmptyOverlay onReset={() => {}} onRecenter={() => {}} />);
    expect(screen.getByText(/no cases in this view/i)).toBeInTheDocument();
  });

  it("calls onReset when the reset button is clicked", () => {
    const onReset = vi.fn();
    render(<MapEmptyOverlay onReset={onReset} onRecenter={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /reset filters/i }));
    expect(onReset).toHaveBeenCalledOnce();
  });

  it("calls onRecenter when the recenter button is clicked", () => {
    const onRecenter = vi.fn();
    render(<MapEmptyOverlay onReset={() => {}} onRecenter={onRecenter} />);
    fireEvent.click(screen.getByRole("button", { name: /recenter/i }));
    expect(onRecenter).toHaveBeenCalledOnce();
  });

  it("has no a11y violations", async () => {
    const { container } = render(<MapEmptyOverlay onReset={() => {}} onRecenter={() => {}} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
