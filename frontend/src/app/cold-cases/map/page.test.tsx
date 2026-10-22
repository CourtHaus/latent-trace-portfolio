import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

vi.mock("@/components/map/ClientMap", () => ({
  ClientMap: vi.fn(() => <div data-testid="client-map-stub" />),
}));

import ColdCaseMapPage, { buildMapQuery } from "./page";
import { apiFetch } from "@/lib/api";
import { ClientMap } from "@/components/map/ClientMap";

const mapResponseSample = {
  mode: "points",
  clusters: [],
  meta: { bbox: null, returned: 2, truncated: false, total_unfiltered: 508 },
  data: [
    {
      case_id: 1,
      slug: "jane-doe-richmond-va-1998",
      case_name: "Jane Doe",
      case_type: "homicide",
      incident_date: "1998-05-14",
      latitude: 37.5,
      longitude: -77.4,
      state: "VA",
      city: "Richmond",
      victim_genders: ["Female"],
      victim_races: ["White"],
    },
  ],
};

const filterOptionsSample = {
  case_types: ["homicide", "missing-person"],
  cities: ["Richmond", "Norfolk"],
  genders: ["Female", "Male"],
  races: ["White", "Black"],
  states: ["VA"],
  year_range: { min: 1958, max: 2023 },
};

describe("buildMapQuery", () => {
  it("returns empty string for no params", () => {
    expect(buildMapQuery({})).toBe("");
  });

  it("serializes bbox as-is", () => {
    const q = buildMapQuery({ bbox: "-80,37,-77,39" });
    expect(decodeURIComponent(q)).toContain("bbox=-80,37,-77,39");
  });

  it("clamps an out-of-range bbox to valid lon/lat (zoomed-out world wrap)", () => {
    // Longitudes past ±180 (and lats past ±90) otherwise 422 from the API.
    const q = buildMapQuery({ bbox: "-187.2949,19.7253,-38.6719,64.3589" });
    expect(decodeURIComponent(q)).toContain("bbox=-180.0000,19.7253,-38.6719,64.3589");
  });

  it("drops a malformed bbox rather than forwarding it", () => {
    expect(buildMapQuery({ bbox: "not,a,bbox" })).toBe("");
  });

  it("joins array filters as comma-separated", () => {
    const q = buildMapQuery({ case_type: ["homicide", "missing-person"] });
    expect(decodeURIComponent(q)).toContain("case_type=homicide,missing-person");
  });

  it("forwards source_system as comma-separated string", () => {
    const q = buildMapQuery({ source_system: "VSPCCD_VA,BCOUNTY_MD_PD" });
    expect(decodeURIComponent(q)).toContain("source_system=VSPCCD_VA,BCOUNTY_MD_PD");
  });

  it("joins source_system array with comma", () => {
    const q = buildMapQuery({ source_system: ["VSPCCD_VA", "BCOUNTY_MD_PD"] });
    expect(decodeURIComponent(q)).toContain("source_system=VSPCCD_VA,BCOUNTY_MD_PD");
  });

  it("forwards precision as a comma-separated filter", () => {
    const q = buildMapQuery({ precision: ["landmark", "zip"] });
    expect(decodeURIComponent(q)).toContain("precision=landmark,zip");
  });
});

describe("ColdCaseMapPage", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(ClientMap).mockClear();
  });

  it("fetches map + filter-options + facet-counts, defaulting zoom so the map starts in cluster mode", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(mapResponseSample)
      .mockResolvedValueOnce(filterOptionsSample)
      .mockResolvedValueOnce({
        case_type: [],
        state: [],
        gender: [],
        race: [],
        precision: [],
        weapon: [],
        location_type: [],
        source_system: [],
        geocoded: 400,
        total: 508,
      });

    const tree = await ColdCaseMapPage({ searchParams: Promise.resolve({}) });
    render(tree);

    expect(apiFetch).toHaveBeenCalledTimes(3);
    // A bare load must still carry zoom — without it the API returns the
    // capped point set and the national view silently truncates.
    expect(vi.mocked(apiFetch).mock.calls[0]?.[0]).toBe("/api/v1/cold-cases/map?zoom=7");
    expect(vi.mocked(apiFetch).mock.calls[1]?.[0]).toBe("/api/v1/cold-cases/filter-options");
    expect(vi.mocked(apiFetch).mock.calls[2]?.[0]).toBe("/api/v1/cold-cases/facet-counts");

    expect(ClientMap).toHaveBeenCalledWith(
      expect.objectContaining({
        initialMode: "points",
        initialData: mapResponseSample.data,
        initialClusters: [],
        filterOptions: filterOptionsSample,
        totalAll: 508,
        initialBbox: null,
        initialZoom: 7,
        mapped: 400,
        coverageTotal: 508,
        unresolved: 108,
      }),
      undefined,
    );
  });

  it("passes requested zoom to the client map for deep-link restoration", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(mapResponseSample)
      .mockResolvedValueOnce(filterOptionsSample);

    const tree = await ColdCaseMapPage({
      searchParams: Promise.resolve({ bbox: "-80,37,-77,39", zoom: "12" }),
    });
    render(tree);

    expect(ClientMap).toHaveBeenCalledWith(
      expect.objectContaining({
        initialBbox: null,
        initialZoom: 12,
      }),
      undefined,
    );
  });

  it("forwards filter params to the map fetch but NOT the filter-options fetch", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(mapResponseSample)
      .mockResolvedValueOnce(filterOptionsSample);

    await ColdCaseMapPage({
      searchParams: Promise.resolve({ year_min: "1990", gender: "Female" }),
    });

    const mapUrl = vi.mocked(apiFetch).mock.calls[0]?.[0] as string;
    expect(mapUrl).toContain("year_min=1990");
    expect(mapUrl).toContain("gender=Female");

    const foUrl = vi.mocked(apiFetch).mock.calls[1]?.[0] as string;
    expect(foUrl).toBe("/api/v1/cold-cases/filter-options");
  });
});
