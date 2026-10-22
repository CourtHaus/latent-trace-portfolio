import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type FilterOptions = components["schemas"]["FilterOptionsResponse"];

/**
 * React.cache-wrapped fetch of /filter-options. Dedups across all server
 * components in the same request tree (StatusStrip, SiteFooter, landing page).
 * The endpoint is also browser-cached 1hr + SWR 24hr per A4's Cache-Control,
 * so this also improves cold-load performance.
 */
export const getFilterOptions = cache(async (): Promise<FilterOptions> => {
  return apiFetch<FilterOptions>("/api/v1/cold-cases/filter-options", {
    next: { revalidate: READ_REVALIDATE_SECONDS },
  });
});

// Build-time / fallback variant for chrome that renders on every route
// (StatusStrip, SiteFooter). The chrome is inherited by the static _not-found
// page; if the API is unreachable during prerender, returning null lets the
// components render placeholder content instead of failing the whole build.
export const getFilterOptionsOrNull = cache(
  async (): Promise<FilterOptions | null> => {
    try {
      return await apiFetch<FilterOptions>("/api/v1/cold-cases/filter-options", {
        next: { revalidate: READ_REVALIDATE_SECONDS },
      });
    } catch {
      return null;
    }
  },
);
