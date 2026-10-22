import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type CoverageHistogram = components["schemas"]["CoverageHistogramResponse"];
export type CoverageBucket = components["schemas"]["CoverageBucket"];

/** React.cache-wrapped fetch of /coverage-histogram (state x decade counts).
 *
 *  Resilient by design: on any fetch failure it returns an empty histogram
 *  rather than throwing, so a single unavailable aggregate never fails the
 *  whole landing prerender (the page omits the Coverage section when empty).
 *  This also lets the frontend deploy ahead of the backend route. ISR
 *  revalidation backfills real data once the endpoint is live. */
export const getCoverageHistogram = cache(async (): Promise<CoverageHistogram> => {
  try {
    return await apiFetch<CoverageHistogram>("/api/v1/cold-cases/coverage-histogram", {
      next: { revalidate: READ_REVALIDATE_SECONDS },
    });
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        `[getCoverageHistogram] fetch failed (${String(err)}); omitting the Coverage section.`,
      );
    }
    return { buckets: [] };
  }
});
