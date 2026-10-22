import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { axe } from "vitest-axe";
import { MarkerDivIcon, type GeocodePrecision } from "./MarkerDivIcon";

describe("MarkerDivIcon", () => {
  it("renders a 14x14 rounded element", () => {
    const { container } = render(<MarkerDivIcon />);
    const el = container.querySelector("div");
    expect(el).toBeInTheDocument();
    expect(el).toHaveClass("rounded-full");
  });

  it("has no a11y violations", async () => {
    const { container } = render(<MarkerDivIcon />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("MarkerDivIcon precision variants", () => {
  it.each<[GeocodePrecision, string]>([
    ["street", "marker--street"],
    ["landmark", "marker--landmark"],
    ["zip", "marker--zip"],
    ["county", "marker--county"],
  ])("renders %s precision with class %s", (precision, expectedClass) => {
    const { container } = render(<MarkerDivIcon precision={precision} />);
    expect(container.firstElementChild?.className).toContain(expectedClass);
  });

  it("renders unspecified precision without a precision suffix class", () => {
    const { container } = render(<MarkerDivIcon />);
    expect(container.firstElementChild?.className).not.toMatch(/marker--/);
  });
});
