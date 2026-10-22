import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { axe } from "vitest-axe";
import { CaseTypeCheckboxes } from "./CaseTypeCheckboxes";

const options = ["homicide", "missing-person", "suspicious-death"];

describe("CaseTypeCheckboxes", () => {
  it("renders a checkbox for each option", () => {
    render(<CaseTypeCheckboxes options={options} selected={[]} onChange={vi.fn()} />);
    // Labels are humanized: "homicide" → "Homicide", "missing-person" → "Missing-person"
    expect(screen.getByLabelText("Homicide")).toBeInTheDocument();
    expect(screen.getByLabelText("Missing-person")).toBeInTheDocument();
    expect(screen.getByLabelText("Suspicious-death")).toBeInTheDocument();
  });

  it("marks selected checkboxes as checked", () => {
    render(
      <CaseTypeCheckboxes options={options} selected={["homicide"]} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("Homicide")).toBeChecked();
    expect(screen.getByLabelText("Missing-person")).not.toBeChecked();
  });

  it("invokes onChange with the full new selection when a box is toggled", () => {
    const onChange = vi.fn();
    render(<CaseTypeCheckboxes options={options} selected={[]} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Homicide"));
    expect(onChange).toHaveBeenCalledWith(["homicide"]);
  });

  it("removes a value when an already-checked box is clicked", () => {
    const onChange = vi.fn();
    render(
      <CaseTypeCheckboxes
        options={options}
        selected={["homicide", "missing-person"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByLabelText("Homicide"));
    expect(onChange).toHaveBeenCalledWith(["missing-person"]);
  });

  it("renders nothing when options is empty", () => {
    const { container } = render(
      <CaseTypeCheckboxes options={[]} selected={[]} onChange={vi.fn()} />,
    );
    expect(container.querySelector("fieldset")).not.toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(
      <CaseTypeCheckboxes options={options} selected={["homicide"]} onChange={vi.fn()} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
