import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import ErrorBoundary from "./error";

describe("MapErrorBoundary", () => {
  const sampleError = new Error("upstream failure");

  it("shows a retry prompt", () => {
    render(<ErrorBoundary error={sampleError} reset={vi.fn()} />);
    expect(screen.getByText(/trouble loading the map/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("reset button invokes reset()", () => {
    const reset = vi.fn();
    render(<ErrorBoundary error={sampleError} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledOnce();
  });

  it("has no a11y violations", async () => {
    const { container } = render(<ErrorBoundary error={sampleError} reset={vi.fn()} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
