import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import { VictimRaceCheckboxes } from "./VictimRaceCheckboxes";

const options = ["Black", "White", "Hispanic", "Asian", "Unknown"];

describe("VictimRaceCheckboxes", () => {
  it("renders a checkbox for each option", () => {
    render(<VictimRaceCheckboxes options={options} selected={[]} onChange={vi.fn()} />);
    for (const opt of options) {
      expect(screen.getByLabelText(opt)).toBeInTheDocument();
    }
  });

  it("toggles on click", () => {
    const onChange = vi.fn();
    render(
      <VictimRaceCheckboxes options={options} selected={["White"]} onChange={onChange} />,
    );
    fireEvent.click(screen.getByLabelText("Black"));
    expect(onChange).toHaveBeenCalledWith(["White", "Black"]);
  });

  it("renders nothing when options is empty", () => {
    const { container } = render(
      <VictimRaceCheckboxes options={[]} selected={[]} onChange={vi.fn()} />,
    );
    expect(container.querySelector("fieldset")).not.toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(
      <VictimRaceCheckboxes options={options} selected={["White"]} onChange={vi.fn()} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
