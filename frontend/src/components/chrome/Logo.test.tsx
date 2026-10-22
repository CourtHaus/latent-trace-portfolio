import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Logo } from "./Logo";

describe("Logo", () => {
  it("renders as a link to / by default", () => {
    render(<Logo />);
    const link = screen.getByRole("link", { name: /latent/i });
    expect(link).toHaveAttribute("href", "/");
  });

  it("renders the logo mark and wordmark", () => {
    const { container } = render(<Logo />);
    expect(screen.getByText("Latent Trace")).toBeInTheDocument();
    expect(container.querySelector(".logo-mark")).not.toBeNull();
  });

  it("accepts optional size prop (sm | md)", () => {
    render(<Logo size="sm" />);
    expect(screen.getByText("Latent Trace")).toBeInTheDocument();
  });
});
