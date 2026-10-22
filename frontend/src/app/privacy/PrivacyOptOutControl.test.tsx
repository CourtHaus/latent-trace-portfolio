import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PrivacyOptOutControl } from "./PrivacyOptOutControl";

const optOutMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/analytics/client", () => ({
  optOut: optOutMock,
}));

describe("PrivacyOptOutControl", () => {
  beforeEach(() => {
    window.localStorage.clear();
    optOutMock.mockClear();
  });

  it("shows the opted-out state when localStorage already contains the opt-out flag", async () => {
    window.localStorage.setItem("cs_analytics_optout", "true");

    render(<PrivacyOptOutControl />);

    expect(await screen.findByText(/you are opted out/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /opt out/i })).not.toBeInTheDocument();
  });

  it("calls optOut and switches to the opted-out state when clicked", async () => {
    optOutMock.mockImplementation(() => {
      window.localStorage.setItem("cs_analytics_optout", "true");
    });
    render(<PrivacyOptOutControl />);

    fireEvent.click(await screen.findByRole("button", { name: /opt out/i }));

    expect(optOutMock).toHaveBeenCalledOnce();
    expect(await screen.findByText(/you are opted out/i)).toBeInTheDocument();
  });
});
