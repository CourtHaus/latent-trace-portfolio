import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type YearHistogram = components["schemas"]["YearHistogramResponse"];
export type YearBucket = components["schemas"]["YearBucket"];

/**
 * React.cache-wrapped fetch of /year-histogram — per-year incident counts (+
 * undated remainder). The landing buckets these into decades for the Signal
 * Deck histogram. Cached 1h + SWR 24h server-side.
 */
export const getYearHistogram = cache(async (): Promise<YearHistogram> => {
  return apiFetch<YearHistogram>("/api/v1/cold-cases/year-histogram", {
    next: { revalidate: READ_REVALIDATE_SECONDS },
  });
});

export const getYearHistogramOrNull = cache(
  async (): Promise<YearHistogram | null> => {
    try {
      return await apiFetch<YearHistogram>("/api/v1/cold-cases/year-histogram", {
        next: { revalidate: READ_REVALIDATE_SECONDS },
      });
    } catch {
      return null;
    }
  },
);

/**
 * Aggregate per-year buckets into decade buckets (e.g. 1990 → "90s"). Decades
 * before `groupBefore` are folded into a single leading "‹NN" bucket — the
 * corpus reaches back to ~1911, but those decades are sparse single-case
 * slivers that clutter the chart and collide on the 2-digit label (1910s vs
 * 2010s both "10s"). Folding keeps the count honest while matching the
 * mockup's clean recent-decades view.
 */
export function bucketByDecade(
  buckets: YearBucket[],
  groupBefore?: number,
): { decade: number; label: string; count: number }[] {
  const byDecade = new Map<number, number>();
  let folded = 0;
  for (const b of buckets) {
    const decade = Math.floor(b.year / 10) * 10;
    if (groupBefore != null && decade < groupBefore) {
      folded += b.count;
      continue;
    }
    byDecade.set(decade, (byDecade.get(decade) ?? 0) + b.count);
  }
  const out = [...byDecade.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([decade, count]) => ({
      decade,
      label: `${String(decade % 100).padStart(2, "0")}s`,
      count,
    }));
  if (groupBefore != null && folded > 0) {
    out.unshift({
      decade: groupBefore - 10,
      label: `‹${String(groupBefore % 100).padStart(2, "0")}`,
      count: folded,
    });
  }
  return out;
}
