import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SortSelect } from "./SortSelect";

describe("SortSelect", () => {
  it("renders the current value and fires onChange with the chosen sort", () => {
    const onChange = vi.fn();
    render(<SortSelect value="incident_date_desc" onChange={onChange} />);
    const select = screen.getByLabelText(/sort/i) as HTMLSelectElement;
    expect(select.value).toBe("incident_date_desc");
    fireEvent.change(select, { target: { value: "victim_name_asc" } });
    expect(onChange).toHaveBeenCalledWith("victim_name_asc");
  });
});
