import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Reveal, CountUp } from "./Reveal";

describe("Reveal", () => {
  it("renders children and is visible-by-default for no-JS / SSR", () => {
    render(<Reveal><p>hello</p></Reveal>);
    expect(screen.getByText("hello")).toBeInTheDocument();
  });
  it("CountUp renders its final value as text immediately (SSR-safe)", () => {
    render(<CountUp to={6760} suffix="" />);
    expect(screen.getByText(/6,760/)).toBeInTheDocument();
  });
});
