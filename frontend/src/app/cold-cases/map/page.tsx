import type { Metadata } from "next";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { ClientMap } from "@/components/map/ClientMap";
import { PageLoad } from "@/components/chrome/PageLoad";
import { getFilterOptions } from "@/lib/getFilterOptions";
import { getFacetCountsOrNull, buildFacetCountMaps } from "@/lib/getFacetCounts";
import { DEFAULT_MAP_ZOOM } from "@/lib/mapDefaults";

type ColdCaseMapResponse = components["schemas"]["ColdCaseMapResponse"];

export const metadata: Metadata = {
  title: "Cold Case Map",
  description:
    "Interactive map of unsolved cold cases across participating jurisdictions. Filter by year, case type, and demographics.",
  openGraph: {
    title: "Cold Case Map · Latent Trace",
    description: "Interactive map of unsolved cold cases.",
    type: "website",
  },
  alternates: { canonical: "/cold-cases/map" },
  twitter: {
    card: "summary_large_image",
    title: "Cold Case Map · Latent Trace",
    description: "Interactive map of unsolved cold cases.",
  },
};

/**
 * Clamp a "w,s,e,n" bbox to valid lon/lat ranges. A zoomed-out viewport (or a
 * stale/hand-edited URL) can carry longitudes past ±180 / lats past ±90, which
 * the API rejects with 422. Returns null when the value isn't 4 finite numbers.
 */
function sanitizeBbox(value: string): string | null {
  const parts = value.split(",").map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null;
  const [w, s, e, n] = parts as [number, number, number, number];
  const inRange =
    w >= -180 && w <= 180 && e >= -180 && e <= 180 && s >= -90 && s <= 90 && n >= -90 && n <= 90;
  if (inRange) return value; // already valid — pass through verbatim
  const lng = (v: number) => Math.max(-180, Math.min(180, v));
  const lat = (v: number) => Math.max(-90, Math.min(90, v));
  return [lng(w), lat(s), lng(e), lat(n)].map((v) => v.toFixed(4)).join(",");
}

export function buildMapQuery(
  params: Record<string, string | string[] | undefined>,
): string {
  const forward = new URLSearchParams();
  const singleKeys = ["bbox", "zoom", "year_min", "year_max", "city", "case_type", "gender", "race", "weapon", "location_type", "source_system", "precision"];

  for (const key of singleKeys) {
    const v = params[key];
    if (typeof v === "string" && v !== "") {
      if (key === "bbox") {
        const clamped = sanitizeBbox(v);
        if (clamped) forward.append(key, clamped);
      } else {
        forward.append(key, v);
      }
    } else if (Array.isArray(v) && v.length > 0) {
      forward.append(key, v.join(","));
    }
  }

  const qs = forward.toString();
  return qs ? `?${qs}` : "";
}

export default async function ColdCaseMapPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;

  // Zoom must always reach the API — it decides cluster vs point mode. On a
  // fresh load (no ?zoom) default to DEFAULT_MAP_ZOOM so the first national
  // view is server-aggregated clusters, never a silently-truncated point set.
  const zoomParam =
    typeof params.zoom === "string" && params.zoom !== ""
      ? params.zoom
      : String(DEFAULT_MAP_ZOOM);
  const parsedZoom = Number.parseInt(zoomParam, 10);
  const initialZoom = Number.isFinite(parsedZoom) ? parsedZoom : DEFAULT_MAP_ZOOM;
  const mapQuery = buildMapQuery({ ...params, zoom: String(initialZoom) });

  const [mapResp, filterOptions, facetCounts] = await Promise.all([
    apiFetch<ColdCaseMapResponse>(`/api/v1/cold-cases/map${mapQuery}`, {
      next: { revalidate: READ_REVALIDATE_SECONDS },
    }),
    getFilterOptions(),
    getFacetCountsOrNull(params),
  ]);
  const facetCountMaps = facetCounts ? buildFacetCountMaps(facetCounts) : null;

  // Page-head coverage stats from the filter-scoped facet counts (geocoded =
  // mapped). Falls back to the map response's unfiltered total if the count
  // fetch failed.
  const total = facetCounts?.total ?? mapResp.meta.total_unfiltered;
  const mapped = facetCounts?.geocoded ?? null;
  const unresolved = mapped != null ? total - mapped : null;

  return (
    <PageLoad>
      <main>
        <ClientMap
          initialMode={mapResp.mode}
          initialData={mapResp.data}
          initialClusters={mapResp.clusters}
          filterOptions={filterOptions}
          facetCounts={facetCountMaps}
          totalAll={mapResp.meta.total_unfiltered}
          initialBbox={mapResp.meta.bbox}
          initialZoom={initialZoom}
          mapped={mapped}
          coverageTotal={total}
          unresolved={unresolved}
        />
      </main>
    </PageLoad>
  );
}
