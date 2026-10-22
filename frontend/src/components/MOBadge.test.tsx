import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MOBadge } from "./MOBadge";

describe("MOBadge", () => {
  it("renders confident value with field label", () => {
    render(<MOBadge field="Weapon" value="firearm" lowConfidence={false} />);
    expect(screen.getByText("Weapon:")).toBeInTheDocument();
    expect(screen.getByText("firearm")).toBeInTheDocument();
  });

  it("renders low-confidence value with uncertain marker", () => {
    render(<MOBadge field="Weapon" value="firearm" lowConfidence={true} />);
    expect(screen.getByText("firearm")).toBeInTheDocument();
    expect(screen.getByText(/uncertain/i)).toBeInTheDocument();
  });

  it("returns null for unknown value (no badge per card contract)", () => {
    const { container } = render(
      <MOBadge field="Weapon" value="unknown" lowConfidence={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null for null value (no badge per card contract)", () => {
    const { container } = render(
      <MOBadge field="Weapon" value={null} lowConfidence={true} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("supports size variant 'card' (text-xs) and 'detail' (text-sm)", () => {
    const { rerender } = render(
      <MOBadge field="Weapon" value="firearm" lowConfidence={false} size="card" />
    );
    expect(screen.getByTestId("mo-badge").className).toMatch(/text-xs/);
    rerender(
      <MOBadge field="Weapon" value="firearm" lowConfidence={false} size="detail" />
    );
    expect(screen.getByTestId("mo-badge").className).toMatch(/text-sm/);
  });
});
