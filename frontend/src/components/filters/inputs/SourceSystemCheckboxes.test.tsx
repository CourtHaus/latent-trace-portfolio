import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourceSystemCheckboxes } from "./SourceSystemCheckboxes";

describe("SourceSystemCheckboxes", () => {
  const options = [
    { code: "BCOUNTY_MD_PD", name: "Baltimore County PD" },
    { code: "AACO_MD_PD", name: "Anne Arundel County PD" },
    { code: "VSPCCD_VA", name: "Virginia State Police Cold Case DB" },
  ];

  it("renders nothing when options is empty", () => {
    const { container } = render(
      <SourceSystemCheckboxes options={[]} selected={[]} onChange={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the user-visible name, not the code", () => {
    render(
      <SourceSystemCheckboxes options={options} selected={[]} onChange={() => {}} />,
    );
    expect(screen.getByLabelText("Baltimore County PD")).toBeInTheDocument();
    expect(screen.queryByLabelText("BCOUNTY_MD_PD")).toBeNull();
  });

  it("toggles by code, not by name", () => {
    const onChange = vi.fn();
    render(
      <SourceSystemCheckboxes options={options} selected={[]} onChange={onChange} />,
    );
    fireEvent.click(screen.getByLabelText("Baltimore County PD"));
    expect(onChange).toHaveBeenCalledWith(["BCOUNTY_MD_PD"]);
  });

  it("removes a selected code on second click", () => {
    const onChange = vi.fn();
    render(
      <SourceSystemCheckboxes
        options={options}
        selected={["AACO_MD_PD"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByLabelText("Anne Arundel County PD"));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
