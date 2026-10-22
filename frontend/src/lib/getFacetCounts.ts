import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type FacetCounts = components["schemas"]["FacetCountsResponse"];
export type FacetCount = components["schemas"]["FacetCount"];

/** value → case count, for keying rail facet counts by option string. */
export type FacetCountMap = Record<string, number>;

function toCountMap(facets: FacetCount[] | undefined): FacetCountMap {
  const map: FacetCountMap = {};
  // Tolerate a missing array — e.g. an API briefly behind the frontend that
  // doesn't yet return a newer facet dimension. Degrade to "no counts" for
  // that dimension instead of throwing and 500-ing the page.
  if (!Array.isArray(facets)) return map;
  for (const f of facets) map[f.value] = f.count;
  return map;
}

/** Per-rail-dimension count maps. Keys match the corresponding filter-option
 *  strings (gender/race canonicalized, source_system keyed by code). */
export interface FacetCountMaps {
  caseType: FacetCountMap;
  gender: FacetCountMap;
  race: FacetCountMap;
  weapon: FacetCountMap;
  locationType: FacetCountMap;
  sourceSystem: FacetCountMap;
  precision: FacetCountMap;
}

export function buildFacetCountMaps(facets: FacetCounts): FacetCountMaps {
  return {
    caseType: toCountMap(facets.case_type),
    gender: toCountMap(facets.gender),
    race: toCountMap(facets.race),
    weapon: toCountMap(facets.weapon),
    locationType: toCountMap(facets.location_type),
    sourceSystem: toCountMap(facets.source_system),
    precision: toCountMap(facets.precision),
  };
}

/**
 * React.cache-wrapped fetch of /facet-counts — unscoped per-facet case counts
 * (case_type, state, gender, precision) + geocoded/total scalars. Drives the
 * landing jurisdiction bars and the filter-rail counts. Cached 1h + SWR 24h
 * server-side (only changes on ingestion).
 */
export const getFacetCounts = cache(async (): Promise<FacetCounts> => {
  return apiFetch<FacetCounts>("/api/v1/cold-cases/facet-counts", {
    next: { revalidate: READ_REVALIDATE_SECONDS },
  });
});

// Filter dimensions the facet-counts endpoint accepts — a subset of the list
// query (no pagination/sort, so counts cache per filter-combination, not per page).
const FILTER_KEYS = [
  "year_min",
  "year_max",
  "city",
  "state",
  "case_type",
  "gender",
  "race",
  "weapon",
  "location_type",
  "source_system",
  "precision",
  "q",
] as const;

function buildFacetCountsQuery(
  params: Record<string, string | string[] | undefined>,
): string {
  const forward = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = params[key];
    if (typeof v === "string" && v !== "") {
      forward.append(key, v);
    } else if (Array.isArray(v) && v.length > 0) {
      forward.append(key, v.join(","));
    }
  }
  const qs = forward.toString();
  return qs ? `?${qs}` : "";
}

/**
 * Faceted counts scoped by the current filters (each facet excludes its own
 * selection server-side). Pass the page's searchParams so counts update as
 * filters change; omit for the unfiltered corpus totals. Returns null on
 * failure so the rail still renders.
 */
export const getFacetCountsOrNull = cache(
  async (
    searchParams?: Record<string, string | string[] | undefined>,
  ): Promise<FacetCounts | null> => {
    const query = searchParams ? buildFacetCountsQuery(searchParams) : "";
    try {
      return await apiFetch<FacetCounts>(`/api/v1/cold-cases/facet-counts${query}`, {
        next: { revalidate: READ_REVALIDATE_SECONDS },
      });
    } catch {
      return null;
    }
  },
);
