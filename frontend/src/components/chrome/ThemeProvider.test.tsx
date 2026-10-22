import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ThemeProvider } from "./ThemeProvider";

const providerProps: Array<Record<string, unknown>> = [];

vi.mock("next-themes", () => ({
  ThemeProvider: ({
    children,
    ...props
  }: {
    children: ReactNode;
    [key: string]: unknown;
  }) => {
    providerProps.push(props);
    return <>{children}</>;
  },
}));

describe("ThemeProvider", () => {
  it("forces dark for the Instrument redesign (light derivation pending)", () => {
    providerProps.length = 0;

    render(
      <ThemeProvider>
        <div>content</div>
      </ThemeProvider>,
    );

    expect(providerProps[0]).toMatchObject({
      forcedTheme: "dark",
      enableSystem: false,
    });
  });
});
