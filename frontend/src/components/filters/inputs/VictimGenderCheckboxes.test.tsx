import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import { VictimGenderCheckboxes } from "./VictimGenderCheckboxes";

// Raw API values; the component humanizes the labels but toggles the raw value.
const options = ["F", "M", "unknown"];

describe("VictimGenderCheckboxes", () => {
  it("renders a humanized label for each raw option", () => {
    render(<VictimGenderCheckboxes options={options} selected={[]} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Female")).toBeInTheDocument();
    expect(screen.getByLabelText("Male")).toBeInTheDocument();
    expect(screen.getByLabelText("Unknown")).toBeInTheDocument();
  });

  it("toggles using the raw value, not the humanized label", () => {
    const onChange = vi.fn();
    render(
      <VictimGenderCheckboxes options={options} selected={["F"]} onChange={onChange} />,
    );
    fireEvent.click(screen.getByLabelText("Male"));
    expect(onChange).toHaveBeenCalledWith(["F", "M"]);
  });

  it("renders nothing when options is empty", () => {
    const { container } = render(
      <VictimGenderCheckboxes options={[]} selected={[]} onChange={vi.fn()} />,
    );
    expect(container.querySelector("fieldset")).not.toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(
      <VictimGenderCheckboxes options={options} selected={["F"]} onChange={vi.fn()} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
