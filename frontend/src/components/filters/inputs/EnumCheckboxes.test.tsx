import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { EnumCheckboxes } from "./EnumCheckboxes";

describe("EnumCheckboxes", () => {
  it("renders nothing when options array is empty", () => {
    const { container } = render(
      <EnumCheckboxes legend="Weapon" options={[]} selected={[]} onChange={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders each option as a checkbox under the legend", () => {
    render(
      <EnumCheckboxes
        legend="Weapon"
        options={["firearm", "knife", "blunt"]}
        selected={[]}
        onChange={() => {}}
      />
    );
    expect(screen.getByText("Weapon")).toBeInTheDocument();
    expect(screen.getByLabelText("firearm")).toBeInTheDocument();
    expect(screen.getByLabelText("knife")).toBeInTheDocument();
    expect(screen.getByLabelText("blunt")).toBeInTheDocument();
  });

  it("toggles a value via onChange when a box is clicked", () => {
    const onChange = vi.fn();
    render(
      <EnumCheckboxes
        legend="Weapon"
        options={["firearm", "knife"]}
        selected={["firearm"]}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByLabelText("knife"));
    expect(onChange).toHaveBeenCalledWith(["firearm", "knife"]);
  });

  it("removes a value via onChange when a checked box is clicked", () => {
    const onChange = vi.fn();
    render(
      <EnumCheckboxes
        legend="Weapon"
        options={["firearm", "knife"]}
        selected={["firearm", "knife"]}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByLabelText("firearm"));
    expect(onChange).toHaveBeenCalledWith(["knife"]);
  });
});
