import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { CaseTypeBadge } from "./CaseTypeBadge";

describe("CaseTypeBadge", () => {
  it("renders the humanized label for a known type", () => {
    render(<CaseTypeBadge caseType="suspicious_death" />);
    expect(screen.getByText("Suspicious Death")).toBeInTheDocument();
  });

  it("title-cases an unknown type", () => {
    render(<CaseTypeBadge caseType="cold_case" />);
    expect(screen.getByText("Cold Case")).toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(<CaseTypeBadge caseType="homicide" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
