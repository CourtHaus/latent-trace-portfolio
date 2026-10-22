import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type SourceSummaryItem = components["schemas"]["SourceSummaryItem"];
export type SourcesSummaryResponse = components["schemas"]["SourcesSummaryResponse"];

/**
 * Per-source aggregates for the methodology page. Cached by React across
 * server-component fetches in the same request.
 */
export const getSourcesSummary = cache(
  async (): Promise<SourcesSummaryResponse> => {
    return apiFetch<SourcesSummaryResponse>("/api/v1/cold-cases/sources-summary", {
      next: { revalidate: READ_REVALIDATE_SECONDS },
    });
  },
);

/** Resilient variant: returns null instead of throwing when the fetch fails, so
 *  a decorative consumer (the landing's Provenance section) degrades gracefully
 *  rather than failing the whole page on a transient API blip (e.g. a Cloud Run
 *  cold-start 500). The methodology page keeps the throwing variant, where the
 *  source aggregates are the actual content. */
export const getSourcesSummaryOrNull = cache(
  async (): Promise<SourcesSummaryResponse | null> => {
    try {
      return await getSourcesSummary();
    } catch (err) {
      if (process.env.NODE_ENV !== "production") {
        console.warn(`[getSourcesSummaryOrNull] fetch failed: ${String(err)}`);
      }
      return null;
    }
  },
);
