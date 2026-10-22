import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Heatmap } from "./Heatmap";

describe("Heatmap", () => {
  it("renders one cell per row*col with an accessible label", () => {
    const rows = ["OH", "CO"];
    const cols = ["90s", "00s", "10s"];
    const values = [[0.2, 0.6, 1], [0.1, 0.3, 0.5]];
    const { getByLabelText, container } = render(
      <Heatmap rows={rows} cols={cols} values={values} />,
    );
    expect(getByLabelText(/density by jurisdiction/i)).toBeInTheDocument();
    expect(container.querySelectorAll("[title]").length).toBe(rows.length * cols.length);
  });
});
