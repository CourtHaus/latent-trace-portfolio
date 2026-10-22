import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";
import { YearRange } from "./YearRange";

describe("YearRange", () => {
  it("renders min + max inputs with current values", () => {
    render(<YearRange yearMin={1990} yearMax={2010} onChange={vi.fn()} />);
    expect(screen.getByLabelText(/minimum year/i)).toHaveValue(1990);
    expect(screen.getByLabelText(/maximum year/i)).toHaveValue(2010);
  });

  it("invokes onChange debounced after user types", async () => {
    const onChange = vi.fn();
    render(<YearRange yearMin={null} yearMax={null} onChange={onChange} />);
    const minInput = screen.getByLabelText(/minimum year/i);
    fireEvent.change(minInput, { target: { value: "1998" } });
    // 150ms debounce window
    await waitFor(
      () => expect(onChange).toHaveBeenCalledWith({ yearMin: 1998, yearMax: null }),
      { timeout: 300 },
    );
  });

  it("clears a field when the input is emptied", async () => {
    const onChange = vi.fn();
    render(<YearRange yearMin={1998} yearMax={2010} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText(/minimum year/i), { target: { value: "" } });
    await waitFor(
      () => expect(onChange).toHaveBeenCalledWith({ yearMin: null, yearMax: 2010 }),
      { timeout: 300 },
    );
  });

  it("has no a11y violations", async () => {
    const { container } = render(<YearRange yearMin={null} yearMax={null} onChange={vi.fn()} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders disabled inputs with 'No dated cases' placeholder when bounds are both null", () => {
    render(
      <YearRange
        yearMin={null}
        yearMax={null}
        bounds={{ min: null, max: null }}
        onChange={vi.fn()}
      />,
    );
    const inputs = screen.getAllByRole("spinbutton");
    for (const input of inputs) {
      expect(input).toBeDisabled();
      expect(input).toHaveAttribute("placeholder", expect.stringContaining("No dated"));
    }
  });

  it("renders bounds as placeholder when provided", () => {
    render(
      <YearRange
        yearMin={null}
        yearMax={null}
        bounds={{ min: 1958, max: 2023 }}
        onChange={vi.fn()}
      />,
    );
    const minInput = screen.getByLabelText("Minimum year");
    const maxInput = screen.getByLabelText("Maximum year");
    expect(minInput).toHaveAttribute("placeholder", "1958");
    expect(maxInput).toHaveAttribute("placeholder", "2023");
    expect(minInput).not.toBeDisabled();
  });

  it("falls back to 'From'/'To' placeholders when bounds prop is not provided (backward compat)", () => {
    render(<YearRange yearMin={null} yearMax={null} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Minimum year")).toHaveAttribute("placeholder", "From");
    expect(screen.getByLabelText("Maximum year")).toHaveAttribute("placeholder", "To");
  });
});
