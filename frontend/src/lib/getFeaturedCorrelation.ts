import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";
import type { JointPlotProps } from "@/components/landing/viz/JointPlot";
import { SAMPLE_CORRELATION } from "@/components/landing/viz/JointPlot";

type CorrelationCandidates =
  components["schemas"]["CorrelationCandidatesResponse"];

// Featured case for the landing joint plot. Chosen (2026-06-08) as a published
// case with a rich candidate pool (146) and 5 graded leads — Chesterfield County
// VA, case 65075. Re-pick by querying /correlation-candidates if the data shifts.
export const FEATURED_CASE_ID = 65075;

const clamp01 = (n: number) => (n < 0 ? 0 : n > 1 ? 1 : n);

// Candidate-pool bounds, used to normalize scatter coordinates to 0..1.
// These MUST track the correlation engine's hard filters in
// src/casesignal/correlation/config.py (CORRELATION_GEO_MILES / _TIME_YEARS).
// score is normalized by the response's score_max (data-driven), but these two
// bounds aren't echoed in the payload, so keep them in sync if the engine tunes.
const GEO_MILES_MAX = 50;
const TIME_YEARS_MAX = 20;

export function mapCorrelationToJointPlot(
  d: CorrelationCandidates,
): JointPlotProps {
  const sm = d.score_max ?? 10;
  return {
    points: d.candidates.map((c) => ({
      distance: clamp01(c.distance_miles / GEO_MILES_MAX),
      yearsApart: clamp01(c.years_apart / TIME_YEARS_MAX),
      score: clamp01(c.score / sm),
    })),
    leads: d.leads.map((l) => ({
      id: `CS-${l.case_id}`,
      name: l.victim_primary_name ?? "Unidentified",
      distanceMi: Math.round(l.distance_miles),
      yearsApart: l.years_apart,
      score: clamp01(l.score / sm),
    })),
  };
}

/** Warn (dev only) when the featured case stops yielding live data, so a
 *  silent fallback to SAMPLE_CORRELATION doesn't hide a misconfigured/unpublished
 *  FEATURED_CASE_ID. No-op in production to avoid log noise. */
function warnFallback(reason: string): void {
  if (process.env.NODE_ENV !== "production") {
    console.warn(
      `[getFeaturedCorrelation] case ${FEATURED_CASE_ID}: ${reason}; using SAMPLE_CORRELATION. Re-pick FEATURED_CASE_ID if the case was unpublished.`,
    );
  }
}

/** Real featured-case joint-plot data; falls back to the deterministic sample
 *  if the fetch fails or the pool is empty (section never breaks). */
export const getFeaturedCorrelation = cache(
  async (): Promise<JointPlotProps> => {
    try {
      const d = await apiFetch<CorrelationCandidates>(
        `/api/v1/cold-cases/${FEATURED_CASE_ID}/correlation-candidates`,
        { next: { revalidate: READ_REVALIDATE_SECONDS } },
      );
      if (!d.candidates.length) {
        warnFallback("empty candidate pool");
        return SAMPLE_CORRELATION;
      }
      return mapCorrelationToJointPlot(d);
    } catch (err) {
      warnFallback(`fetch failed (${String(err)})`);
      return SAMPLE_CORRELATION;
    }
  },
);
