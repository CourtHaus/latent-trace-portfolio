import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Ridgeline } from "./Ridgeline";
describe("Ridgeline", () => {
  it("renders an accessible img with decade labels", () => {
    const { container, getByRole } = render(<Ridgeline rows={[
      { label: "2000s", weight: 0.9, peak: false, count: 90 }, { label: "2010s", weight: 1, peak: true, count: 100 },
    ]} />);
    expect(getByRole("img")).toHaveAttribute("aria-label", expect.stringContaining("2010s"));
    expect(container.querySelector("text")?.textContent).toBeTruthy();
  });
});
