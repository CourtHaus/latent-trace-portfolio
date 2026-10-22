import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

vi.mock("next/navigation", () => ({
  redirect: vi.fn((_url: string) => {
    throw new Error(`__REDIRECT__:${_url}`);
  }),
}));

vi.mock("@/components/list/ListClient", () => ({
  ListClient: vi.fn(() => <div data-testid="list-client-stub" />),
}));

vi.mock("@/components/list/ListPagination", () => ({
  ListPagination: vi.fn(() => <div data-testid="list-pagination-stub" />),
}));

vi.mock("@/lib/getDatasetCounts", () => ({
  getDatasetCountsOrNull: vi.fn(),
}));

import ColdCasesPage, {
  buildListQuery,
  generateMetadata,
} from "./page";
import { apiFetch } from "@/lib/api";
import { ListClient } from "@/components/list/ListClient";
import { ListPagination } from "@/components/list/ListPagination";
import { redirect } from "next/navigation";
import { getDatasetCountsOrNull } from "@/lib/getDatasetCounts";

const listResponse = {
  meta: { total: 508, total_unfiltered: 508, offset: 0, limit: 50 },
  data: Array.from({ length: 50 }, (_, i) => ({
    case_id: i + 1,
    slug: `case-${i + 1}`,
    case_name: `Case ${i + 1}`,
    case_type: "homicide",
    incident_date: "1998-05-14",
    city: "Richmond",
    state: "VA",
  })),
};

const filterOptionsResponse = {
  case_types: ["homicide"],
  cities: ["Richmond"],
  genders: ["Female"],
  races: ["White"],
  states: ["OH", "CO", "VA"],
  year_range: { min: 1961, max: 2023 },
};

describe("buildListQuery", () => {
  it("returns base query for no params", () => {
    const q = buildListQuery({});
    expect(q).toContain("limit=25");
    expect(q).toContain("offset=0");
    expect(q).toContain("sort=incident_date_desc");
  });

  it("translates ?page=3 to offset=50", () => {
    const q = buildListQuery({ page: "3" });
    expect(q).toContain("offset=50");
    expect(q).toContain("limit=25");
  });

  it("forwards filter params verbatim", () => {
    const q = buildListQuery({ year_min: "1990", gender: "Female,Male" });
    expect(q).toContain("year_min=1990");
    expect(decodeURIComponent(q)).toContain("gender=Female,Male");
  });

  it("joins array values with comma", () => {
    const q = buildListQuery({ case_type: ["homicide", "missing-person"] });
    expect(decodeURIComponent(q)).toContain("case_type=homicide,missing-person");
  });

  it("handles invalid page (non-numeric falls back to 1)", () => {
    const q = buildListQuery({ page: "garbage" });
    expect(q).toContain("offset=0");
  });

  it("forwards source_system as comma-separated string", () => {
    const q = buildListQuery({ source_system: "VSPCCD_VA,BCOUNTY_MD_PD" });
    expect(decodeURIComponent(q)).toContain("source_system=VSPCCD_VA,BCOUNTY_MD_PD");
  });

  it("forwards precision as a comma-separated filter", () => {
    const q = buildListQuery({ precision: ["street", "county"] });
    expect(decodeURIComponent(q)).toContain("precision=street,county");
  });

  it("joins source_system array with comma", () => {
    const q = buildListQuery({ source_system: ["VSPCCD_VA", "BCOUNTY_MD_PD"] });
    expect(decodeURIComponent(q)).toContain("source_system=VSPCCD_VA,BCOUNTY_MD_PD");
  });
});

describe("generateMetadata", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockResolvedValue(listResponse);
  });

  it("canonical /cold-cases when any filter is set", async () => {
    const meta = await generateMetadata({
      searchParams: Promise.resolve({ year_min: "1990" }),
    });
    expect(meta.alternates?.canonical).toBe("/cold-cases");
  });

  it("canonical self when only page param is set", async () => {
    const meta = await generateMetadata({
      searchParams: Promise.resolve({ page: "3" }),
    });
    expect(meta.alternates?.canonical).toBe("/cold-cases?page=3");
  });

  it("canonical /cold-cases on bare URL", async () => {
    const meta = await generateMetadata({
      searchParams: Promise.resolve({}),
    });
    expect(meta.alternates?.canonical).toBe("/cold-cases");
  });
});

describe("ColdCasesPage", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(ListClient).mockClear();
    vi.mocked(ListPagination).mockClear();
    vi.mocked(redirect).mockClear();
    vi.mocked(getDatasetCountsOrNull).mockReset();
    vi.mocked(getDatasetCountsOrNull).mockResolvedValue({
      totalUnfiltered: 6760,
      geocodedUnfiltered: 6580,
    });
  });

  it("renders the eyebrow + display title", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(listResponse)
      .mockResolvedValueOnce(filterOptionsResponse)
      .mockResolvedValueOnce(null);

    const { getByText, getByRole } = render(
      await ColdCasesPage({ searchParams: Promise.resolve({}) }),
    );
    expect(getByText("Named-victim cold homicides")).toBeInTheDocument();
    expect(getByRole("heading", { level: 1 })).toHaveTextContent(
      "The case register",
    );
  });

  it("renders the stat-rail year span", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(listResponse)
      .mockResolvedValueOnce(filterOptionsResponse)
      .mockResolvedValueOnce(null);

    const { container } = render(
      await ColdCasesPage({ searchParams: Promise.resolve({}) }),
    );
    expect(container.textContent).toMatch(/Named victims/);
    expect(container.textContent).toMatch(/1961–2023/);
  });

  it("renders even when dataset counts are unavailable (Geocoded degrades to placeholder)", async () => {
    vi.mocked(getDatasetCountsOrNull).mockResolvedValue(null);
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(listResponse)
      .mockResolvedValueOnce(filterOptionsResponse)
      .mockResolvedValueOnce(null);

    const { container, getByText, getByRole } = render(
      await ColdCasesPage({ searchParams: Promise.resolve({}) }),
    );
    expect(getByText("Named-victim cold homicides")).toBeInTheDocument();
    expect(getByRole("heading", { level: 1 })).toHaveTextContent(
      "The case register",
    );
    expect(container.textContent).toMatch(/The case register/);
    expect(container.textContent).toMatch(/Incident span/);
    // Geocoded cell degrades to a placeholder glyph rather than 0%.
    expect(container.textContent).toContain("—");
  });

  it("fetches list + filter-options + facet-counts in parallel and renders ListClient + ListPagination", async () => {
    const facetCountsResponse = {
      case_type: [{ value: "homicide", count: 508 }],
      state: [],
      gender: [],
      race: [],
      precision: [],
      weapon: [],
      location_type: [],
      source_system: [{ value: "VSPCCD_VA", count: 508 }],
      geocoded: 507,
      total: 508,
    };
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(listResponse)
      .mockResolvedValueOnce(filterOptionsResponse)
      .mockResolvedValueOnce(facetCountsResponse);

    const tree = await ColdCasesPage({ searchParams: Promise.resolve({}) });
    render(tree);

    expect(apiFetch).toHaveBeenCalledTimes(3);
    expect(vi.mocked(apiFetch).mock.calls[0]?.[0]).toContain("/api/v1/cold-cases?");
    expect(vi.mocked(apiFetch).mock.calls[1]?.[0]).toBe("/api/v1/cold-cases/filter-options");
    expect(vi.mocked(apiFetch).mock.calls[2]?.[0]).toBe("/api/v1/cold-cases/facet-counts");

    expect(ListClient).toHaveBeenCalledWith(
      expect.objectContaining({
        totalFiltered: 508,
        totalUnfiltered: 508,
        filterOptions: filterOptionsResponse,
        facetCounts: expect.objectContaining({
          caseType: { homicide: 508 },
          sourceSystem: { VSPCCD_VA: 508 },
        }),
      }),
      undefined,
    );

    expect(ListPagination).toHaveBeenCalled();
  });

  it("scopes the facet-counts request to the active filters", async () => {
    const emptyFacets = {
      case_type: [],
      state: [],
      gender: [],
      race: [],
      precision: [],
      weapon: [],
      location_type: [],
      source_system: [],
      geocoded: 0,
      total: 0,
    };
    vi.mocked(apiFetch).mockImplementation(async (url: string) => {
      if (url.includes("/facet-counts")) return emptyFacets;
      if (url.includes("/filter-options")) return filterOptionsResponse;
      return listResponse;
    });

    const tree = await ColdCasesPage({
      searchParams: Promise.resolve({ case_type: "homicide", gender: "Female" }),
    });
    render(tree);

    const facetCall = vi
      .mocked(apiFetch)
      .mock.calls.map((c) => c[0] as string)
      .find((u) => u.includes("/facet-counts"));
    expect(facetCall).toContain("case_type=homicide");
    expect(facetCall).toContain("gender=Female");
    // Pagination/sort are NOT forwarded — counts cache per filter-combo, not per page.
    expect(facetCall).not.toContain("limit=");
    expect(facetCall).not.toContain("sort=");
  });

  it("redirects to unfiltered base when offset >= total (out of range)", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        meta: { total: 30, total_unfiltered: 508, offset: 100, limit: 50 },
        data: [],
      })
      .mockResolvedValueOnce(filterOptionsResponse);

    await expect(
      ColdCasesPage({ searchParams: Promise.resolve({ page: "3" }) }),
    ).rejects.toThrow(/__REDIRECT__/);

    expect(vi.mocked(redirect)).toHaveBeenCalled();
    const redirectUrl = vi.mocked(redirect).mock.calls[0]?.[0] as string;
    expect(redirectUrl).toBe("/cold-cases");
  });

  it("redirects preserving filter params when out of range", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        meta: { total: 10, total_unfiltered: 508, offset: 100, limit: 50 },
        data: [],
      })
      .mockResolvedValueOnce(filterOptionsResponse);

    await expect(
      ColdCasesPage({ searchParams: Promise.resolve({ page: "3", gender: "Female" }) }),
    ).rejects.toThrow(/__REDIRECT__/);

    const redirectUrl = vi.mocked(redirect).mock.calls[0]?.[0] as string;
    expect(redirectUrl).toContain("gender=Female");
    expect(redirectUrl).not.toContain("page=");
  });
});
