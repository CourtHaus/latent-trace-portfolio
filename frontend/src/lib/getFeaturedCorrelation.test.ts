import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

import {
  mapCorrelationToJointPlot,
  getFeaturedCorrelation,
  FEATURED_CASE_ID,
} from "./getFeaturedCorrelation";
import { apiFetch } from "@/lib/api";
import { SAMPLE_CORRELATION } from "@/components/landing/viz/JointPlot";

describe("mapCorrelationToJointPlot", () => {
  it("normalizes candidates to 0..1 and maps leads", () => {
    const out = mapCorrelationToJointPlot({
      score_max: 3.5,
      score_floor: 1.5,
      candidates: [{ distance_miles: 25, years_apart: 10, score: 1.75 }],
      leads: [{
        case_id: 1, slug: "x", victim_primary_name: "A. Bowen",
        city: "X", state: "OH", year: 2001, score: 2.1, score_max: 3.5,
        proximity_factor: 0.7, matched_dimensions: [], distance_miles: 12, years_apart: 3,
      }],
    });
    expect(out.points[0]).toEqual({ distance: 0.5, yearsApart: 0.5, score: 0.5 });
    expect(out.leads[0]).toMatchObject({ id: "CS-1", name: "A. Bowen", distanceMi: 12, yearsApart: 3 });
    expect(out.leads[0]!.score).toBeCloseTo(0.6, 5);
  });
  it("clamps out-of-range distance/years to 1", () => {
    const out = mapCorrelationToJointPlot({
      score_max: 3.5, score_floor: 1.5,
      candidates: [{ distance_miles: 60, years_apart: 25, score: 4 }], leads: [],
    });
    expect(out.points[0]).toEqual({ distance: 1, yearsApart: 1, score: 1 });
  });
  it("falls back to 'Unidentified' when victim_primary_name is null", () => {
    const out = mapCorrelationToJointPlot({
      score_max: 3.5, score_floor: 1.5, candidates: [],
      leads: [{
        case_id: 9, slug: "y", victim_primary_name: null, city: null, state: "VA",
        year: 2010, score: 3.0, score_max: 3.5, proximity_factor: 0.4, matched_dimensions: [],
        distance_miles: 4.6, years_apart: 7,
      }],
    });
    expect(out.leads[0]).toMatchObject({ id: "CS-9", name: "Unidentified", distanceMi: 5, yearsApart: 7 });
  });
});

describe("getFeaturedCorrelation (wrapper fallback)", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.spyOn(console, "warn").mockImplementation(() => {}); // dev fallback warn is expected
  });

  it("maps the real response when the pool is non-empty", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      score_max: 3.5,
      score_floor: 1.5,
      candidates: [{ distance_miles: 25, years_apart: 10, score: 1.75 }],
      leads: [],
    });
    const out = await getFeaturedCorrelation();
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/v1/cold-cases/${FEATURED_CASE_ID}/correlation-candidates`,
      expect.anything(),
    );
    expect(out.points[0]).toEqual({ distance: 0.5, yearsApart: 0.5, score: 0.5 });
    expect(out).not.toBe(SAMPLE_CORRELATION);
  });

  it("falls back to SAMPLE_CORRELATION when the candidate pool is empty", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      score_max: 3.5,
      score_floor: 1.5,
      candidates: [],
      leads: [],
    });
    const out = await getFeaturedCorrelation();
    expect(out).toBe(SAMPLE_CORRELATION);
  });

  it("falls back to SAMPLE_CORRELATION when the fetch throws", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("404 Not Found"));
    const out = await getFeaturedCorrelation();
    expect(out).toBe(SAMPLE_CORRELATION);
  });
});
