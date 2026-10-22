import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";

type ListResponse = components["schemas"]["ColdCaseListResponse"];
type MapResponse = components["schemas"]["ColdCaseMapResponse"];

export interface DatasetCounts {
  /** Total cases in the dataset, from /cold-cases list meta.total_unfiltered. */
  totalUnfiltered: number;
  /** Geocoded cases on the map, from /cold-cases/map meta.total_unfiltered. */
  geocodedUnfiltered: number;
}

/**
 * React.cache-wrapped parallel fetch of list + map unfiltered totals.
 * Used by the landing page, the methodology page, and the register to compute
 * geocoded coverage percentage. The register's stat rail is decorative, so it
 * consumes the resilient `getDatasetCountsOrNull` variant below rather than
 * this throwing one.
 * Both underlying endpoints are rate-limited per A0; ?limit=1 means the
 * endpoints skip their SELECT work and only compute the meta COUNTs.
 */
export const getDatasetCounts = cache(async (): Promise<DatasetCounts> => {
  const [listResp, mapResp] = await Promise.all([
    apiFetch<ListResponse>("/api/v1/cold-cases?limit=1", {
      next: { revalidate: READ_REVALIDATE_SECONDS },
    }),
    apiFetch<MapResponse>("/api/v1/cold-cases/map?limit=1", {
      next: { revalidate: READ_REVALIDATE_SECONDS },
    }),
  ]);
  return {
    totalUnfiltered: listResp.meta.total_unfiltered,
    geocodedUnfiltered: mapResp.meta.total_unfiltered,
  };
});

/** Resilient variant: returns null instead of throwing when the count fetch
 *  fails, so a decorative consumer (e.g. the register stat rail) degrades
 *  gracefully rather than failing the whole page. */
export const getDatasetCountsOrNull = cache(async (): Promise<DatasetCounts | null> => {
  try {
    return await getDatasetCounts();
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(`[getDatasetCountsOrNull] count fetch failed: ${String(err)}`);
    }
    return null;
  }
});
