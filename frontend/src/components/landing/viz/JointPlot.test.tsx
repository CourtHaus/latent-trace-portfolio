import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { JointPlot, SAMPLE_CORRELATION } from "./JointPlot";

describe("JointPlot", () => {
  it("renders an accessible scatter and the ranked leads", () => {
    const { getByRole, getAllByText } = render(<JointPlot {...SAMPLE_CORRELATION} />);
    expect(getByRole("img")).toHaveAttribute("aria-label", expect.stringContaining("focal"));
    expect(getAllByText(/0\.\d\d/).length).toBeGreaterThanOrEqual(5);
  });
});
