import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import CaseDetailPage from "./page";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  permanentRedirect: vi.fn(() => {
    throw new Error("NEXT_REDIRECT");
  }),
}));

import { apiFetch, ApiError } from "@/lib/api";
import { notFound, permanentRedirect } from "next/navigation";

const baseCase = {
  case_id: 42,
  slug: "jane-doe-richmond-va-1998",
  source_case_id: "2022-0003209",
  case_name: "Jane Doe",
  case_type: "homicide",
  incident_date: "1998-05-14",
  address: "123 Main St",
  city: "Richmond",
  state: "VA",
  about_text: "Circumstances of the case...",
  latitude: "37.5407",
  longitude: "-77.4360",
  victims: [
    {
      victim_id: 7,
      first_name: "Jane",
      last_name: "Doe",
      gender: "Female",
      height_text: null,
      weight_num: null,
      age_text: "24",
      age_num: 24,
      race: "White",
      eye_color: null,
      hair_color: null,
    },
  ],
  contact: {
    phone: "(804) 555-1234",
    email: "tips@vsp.va.gov",
    address: "700 E Grace St, Richmond, VA",
  },
  extraction: null,
  correlations: [],
};

describe("CaseDetailPage", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(notFound).mockClear();
    vi.mocked(permanentRedirect).mockClear();
  });

  it("happy path — renders hero, victims anchor, tip section, narrative, breadcrumbs, recovery location", async () => {
    vi.mocked(apiFetch).mockResolvedValue(baseCase);
    const tree = await CaseDetailPage({
      params: Promise.resolve({ id: "42", slug: "jane-doe-richmond-va-1998" }),
    });
    const { container } = render(tree);

    expect(screen.getByRole("heading", { level: 1, name: "Jane Doe" })).toBeInTheDocument();
    expect(container.querySelector("#victim-42-7")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /submit a tip/i })).toBeInTheDocument();
    expect(screen.getByText(/Circumstances of the case/)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    // Case has coords → the tall recovery-location map tile renders.
    expect(screen.getByRole("heading", { name: /recovery location/i })).toBeInTheDocument();
  });

  it("no-coords case reflows — victim section renders, recovery location omitted", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseCase,
      latitude: null,
      longitude: null,
    });
    const tree = await CaseDetailPage({
      params: Promise.resolve({ id: "42", slug: "jane-doe-richmond-va-1998" }),
    });
    const { container } = render(tree);

    // Victim section still present (full-width reflow).
    expect(container.querySelector("#victim-42-7")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^victim$/i })).toBeInTheDocument();
    // No map tile when coordinates are absent.
    expect(screen.queryByRole("heading", { name: /recovery location/i })).not.toBeInTheDocument();
  });

  it("no-coords + has-contact — tip goes full-width, not column-3-pinned", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseCase,
      latitude: null,
      longitude: null,
      contact: {
        phone: "(804) 555-1234",
        email: "tips@vsp.va.gov",
        address: "700 E Grace St, Richmond, VA",
      },
    });
    const tree = await CaseDetailPage({
      params: Promise.resolve({ id: "42", slug: "jane-doe-richmond-va-1998" }),
    });
    const { container } = render(tree);

    // Tip section renders...
    expect(screen.getByRole("heading", { name: /submit a tip/i })).toBeInTheDocument();
    // ...and with no map anchoring col 3, nothing is col-3-pinned (the tip reflows full-width).
    expect(container.querySelector(".lg\\:col-start-3")).toBeNull();
  });

  it("does not label every non-Maryland case as Virginia State Police", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...baseCase,
      state: "CO",
      city: "Denver",
      slug: "jane-doe-denver-co-1998",
    });

    const tree = await CaseDetailPage({
      params: Promise.resolve({ id: "42", slug: "jane-doe-denver-co-1998" }),
    });
    render(tree);

    expect(screen.queryByText(/Virginia State Police/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Data source:/)).toHaveTextContent("Public agency source record");
  });


  it("stale slug redirects to canonical", async () => {
    vi.mocked(apiFetch).mockResolvedValue(baseCase);
    try {
      await CaseDetailPage({
        params: Promise.resolve({ id: "42", slug: "outdated-slug" }),
      });
      expect.fail("should have redirected");
    } catch {
      // permanentRedirect throws in our mock
    }
    expect(permanentRedirect).toHaveBeenCalledWith("/cold-cases/42/jane-doe-richmond-va-1998");
  });

  it("non-integer id → notFound", async () => {
    try {
      await CaseDetailPage({
        params: Promise.resolve({ id: "abc", slug: "whatever" }),
      });
      expect.fail("should have called notFound");
    } catch {
      // notFound throws in our mock
    }
    expect(notFound).toHaveBeenCalled();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("ApiError(404) → notFound", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(404, "not found"));
    try {
      await CaseDetailPage({
        params: Promise.resolve({ id: "999", slug: "whatever" }),
      });
      expect.fail("should have called notFound");
    } catch {
      // notFound throws
    }
    expect(notFound).toHaveBeenCalled();
  });

  it("ApiError(500) propagates to error boundary", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(500, "boom"));
    await expect(
      CaseDetailPage({
        params: Promise.resolve({ id: "42", slug: "whatever" }),
      }),
    ).rejects.toThrow(/boom/);
    expect(notFound).not.toHaveBeenCalled();
  });

  it("has no a11y violations on happy path", async () => {
    vi.mocked(apiFetch).mockResolvedValue(baseCase);
    const tree = await CaseDetailPage({
      params: Promise.resolve({ id: "42", slug: "jane-doe-richmond-va-1998" }),
    });
    const { container } = render(tree);
    expect(await axe(container)).toHaveNoViolations();
  });
});
