import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { AnalyticsProvider } from "./AnalyticsProvider";

const { initMock, trackMock } = vi.hoisted(() => ({
  initMock: vi.fn(),
  trackMock: vi.fn(),
}));

vi.mock("@/lib/analytics/client", () => ({
  initAnalytics: initMock,
  track: trackMock,
}));

const pathnameMock = vi.fn(() => "/");
const searchParamsMock = vi.fn(() => new URLSearchParams());

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
  useSearchParams: () => searchParamsMock(),
}));

describe("AnalyticsProvider", () => {
  beforeEach(() => {
    initMock.mockClear();
    trackMock.mockClear();
    pathnameMock.mockReturnValue("/");
    searchParamsMock.mockReturnValue(new URLSearchParams());
  });

  it("initializes analytics on mount", () => {
    render(<AnalyticsProvider>child</AnalyticsProvider>);
    expect(initMock).toHaveBeenCalledOnce();
  });

  it("emits page_viewed with the path", () => {
    pathnameMock.mockReturnValue("/cold-cases");
    render(<AnalyticsProvider>child</AnalyticsProvider>);
    expect(trackMock).toHaveBeenCalledWith("page_viewed", { path: "/cold-cases" });
  });

  it("does NOT include querystring in the path property", () => {
    pathnameMock.mockReturnValue("/cold-cases");
    searchParamsMock.mockReturnValue(new URLSearchParams("q=jane&state=VA"));
    render(<AnalyticsProvider>child</AnalyticsProvider>);
    expect(trackMock).toHaveBeenCalledWith("page_viewed", { path: "/cold-cases" });
  });

  it("renders children", () => {
    const { getByText } = render(<AnalyticsProvider>hello</AnalyticsProvider>);
    expect(getByText("hello")).toBeInTheDocument();
  });
});
