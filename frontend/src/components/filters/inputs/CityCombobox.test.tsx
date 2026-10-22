import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";
import { CityCombobox } from "./CityCombobox";

const cities = ["Richmond", "Norfolk", "Roanoke", "Virginia Beach", "Arlington"];

describe("CityCombobox", () => {
  it("renders an input with current value", () => {
    render(<CityCombobox options={cities} value="Richmond" onChange={vi.fn()} />);
    expect(screen.getByLabelText(/city/i)).toHaveValue("Richmond");
  });

  it("shows filtered suggestions when user types", () => {
    render(<CityCombobox options={cities} value="" onChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/city/i), { target: { value: "Rich" } });
    expect(screen.getByText("Richmond")).toBeInTheDocument();
    expect(screen.queryByText("Norfolk")).not.toBeInTheDocument();
  });

  it("invokes onChange debounced when a suggestion is picked", async () => {
    const onChange = vi.fn();
    render(<CityCombobox options={cities} value="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText(/city/i), { target: { value: "Rich" } });
    fireEvent.click(screen.getByText("Richmond"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("Richmond"), {
      timeout: 300,
    });
  });

  it("clears selection when input is emptied", async () => {
    const onChange = vi.fn();
    render(<CityCombobox options={cities} value="Richmond" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText(/city/i), { target: { value: "" } });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null), {
      timeout: 300,
    });
  });

  it("exposes combobox + listbox/option roles when open", () => {
    render(<CityCombobox options={cities} value="" onChange={vi.fn()} />);
    const input = screen.getByLabelText(/city/i);
    expect(input).toHaveAttribute("role", "combobox");
    fireEvent.change(input, { target: { value: "Rich" } });
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Richmond" })).toBeInTheDocument();
  });

  it("selects via keyboard (ArrowDown + Enter)", async () => {
    const onChange = vi.fn();
    render(<CityCombobox options={cities} value="" onChange={onChange} />);
    const input = screen.getByLabelText(/city/i);
    fireEvent.change(input, { target: { value: "Roa" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input).toHaveValue("Roanoke");
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("Roanoke"), {
      timeout: 300,
    });
  });

  it("closes the list on Escape", () => {
    render(<CityCombobox options={cities} value="" onChange={vi.fn()} />);
    const input = screen.getByLabelText(/city/i);
    fireEvent.change(input, { target: { value: "Rich" } });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(
      <CityCombobox options={cities} value="" onChange={vi.fn()} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
