import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import ErrorBoundary from "./error";

describe("CaseErrorBoundary", () => {
  const sampleError = new Error("upstream timeout");

  it("shows a retry prompt", () => {
    render(<ErrorBoundary error={sampleError} reset={vi.fn()} />);
    expect(screen.getByText(/trouble loading this case/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("invokes reset() when retry button clicked", () => {
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
