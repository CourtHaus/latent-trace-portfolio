import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { SubmitTipSection } from "./SubmitTipSection";

describe("SubmitTipSection", () => {
  it("renders phone + email + address as action links", () => {
    render(<SubmitTipSection
      phone="(804) 555-1234"
      email="tips@vsp.va.gov"
      address="700 E Grace St, Richmond, VA"
    />);
    const phoneLink = screen.getByRole("link", { name: /\(804\) 555-1234/ });
    expect(phoneLink).toHaveAttribute("href", "tel:8045551234");
    const emailLink = screen.getByRole("link", { name: /tips@vsp\.va\.gov/ });
    expect(emailLink).toHaveAttribute("href", "mailto:tips%40vsp.va.gov");
    expect(screen.getByText(/700 E Grace St/)).toBeInTheDocument();
  });

  it("omits fields that are null", () => {
    render(<SubmitTipSection phone="(804) 555-1234" email={null} address={null} />);
    expect(screen.queryByRole("link", { name: /mailto/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/@/)).not.toBeInTheDocument();
  });

  it("renders nothing visible when all fields null", () => {
    const { container } = render(<SubmitTipSection phone={null} email={null} address={null} />);
    expect(container.querySelector("section")).not.toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(<SubmitTipSection
      phone="(804) 555-1234"
      email="tips@vsp.va.gov"
      address="700 E Grace St"
    />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
