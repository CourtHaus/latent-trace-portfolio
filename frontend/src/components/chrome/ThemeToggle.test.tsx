import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const setThemeMock = vi.fn();
vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme: "dark",
    resolvedTheme: "dark",
    setTheme: setThemeMock,
  }),
}));

import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  it("renders a button with accessible label", () => {
    render(<ThemeToggle />);
    const btn = screen.getByRole("button", { name: /toggle theme|theme/i });
    expect(btn).toBeInTheDocument();
  });

  it("calls setTheme with the opposite theme on click", () => {
    setThemeMock.mockClear();
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: /toggle theme|theme/i }));
    expect(setThemeMock).toHaveBeenCalledWith("light");
  });
});
