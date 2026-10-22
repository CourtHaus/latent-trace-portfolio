import { cache } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { ListClient } from "@/components/list/ListClient";
import { ListPagination } from "@/components/list/ListPagination";
import { buildListUrl } from "@/lib/buildListUrl";
import { PageLoad } from "@/components/chrome/PageLoad";
import { getFilterOptions } from "@/lib/getFilterOptions";
import { getFacetCountsOrNull, buildFacetCountMaps } from "@/lib/getFacetCounts";
import { getDatasetCountsOrNull } from "@/lib/getDatasetCounts";
import { StatRail } from "@/components/site/primitives";
import { SORT_LABELS, DEFAULT_SORT } from "@/lib/sortOrder";

type ColdCaseListResponse = components["schemas"]["ColdCaseListResponse"];

const PAGE_SIZE = 25;
const FILTER_DIMENSION_COUNT = 7;

/**
 * Translates Next searchParams into a backend query string.
 * page (1-indexed in URL) → offset = (page - 1) * PAGE_SIZE for backend.
 * Filter params forwarded verbatim; array values comma-joined.
 */
export function buildListQuery(
  params: Record<string, string | string[] | undefined>,
): string {
  const forward = new URLSearchParams();
  const pageRaw = typeof params.page === "string" ? parseInt(params.page, 10) : NaN;
  const page = Number.isFinite(pageRaw) && pageRaw >= 1 ? pageRaw : 1;
  const offset = (page - 1) * PAGE_SIZE;

  forward.set("limit", String(PAGE_SIZE));
  forward.set("offset", String(offset));
  const sort = typeof params.sort === "string" ? params.sort : DEFAULT_SORT;
  forward.set("sort", sort);

  const filterKeys = ["year_min", "year_max", "city", "state", "case_type", "gender", "race", "weapon", "location_type", "source_system", "precision", "q"];
  for (const key of filterKeys) {
    const v = params[key];
    if (typeof v === "string" && v !== "") {
      forward.append(key, v);
    } else if (Array.isArray(v) && v.length > 0) {
      forward.append(key, v.join(","));
    }
  }

  return `?${forward.toString()}`;
}

/**
 * React.cache dedups fetches across generateMetadata + page body within a
 * single RSC render. CRITICAL: both call sites pass the SAME searchParams
 * object (passed unchanged from Next) — normalizing or copying before
 * calling would cause a cache miss and a second fetch.
 */
const getColdCases = cache(
  async (searchParams: Record<string, string | string[] | undefined>) => {
    return apiFetch<ColdCaseListResponse>(
      `/api/v1/cold-cases${buildListQuery(searchParams)}`,
      { next: { revalidate: READ_REVALIDATE_SECONDS } },
    );
  },
);

function hasAnyFilter(
  params: Record<string, string | string[] | undefined>,
): boolean {
  const filterKeys = ["year_min", "year_max", "city", "state", "case_type", "gender", "race", "weapon", "location_type", "source_system", "q"];
  return filterKeys.some((k) => {
    const v = params[k];
    return (typeof v === "string" && v !== "") || (Array.isArray(v) && v.length > 0);
  });
}

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}): Promise<Metadata> {
  const params = await searchParams;

  let canonical: string;
  if (hasAnyFilter(params)) {
    canonical = "/cold-cases";
  } else if (typeof params.page === "string" && params.page !== "" && params.page !== "1") {
    canonical = `/cold-cases?page=${params.page}`;
  } else {
    canonical = "/cold-cases";
  }

  return {
    title: "Cold Cases",
    description:
      "Browse unsolved cold case records by jurisdiction, year, and victim demographics.",
    alternates: { canonical },
    openGraph: {
      title: "Cold Cases · Latent Trace",
      description: "Browse unsolved cold case records by jurisdiction, year, and demographics.",
      url: "/cold-cases",
    },
  };
}

export default async function ColdCasesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;

  const [list, filterOptions, facetCounts, counts] = await Promise.all([
    getColdCases(params),
    getFilterOptions(),
    getFacetCountsOrNull(params),
    getDatasetCountsOrNull(),
  ]);
  // facetCounts are a non-critical enhancement — if the endpoint fails the rail
  // still renders, just without per-facet counts.
  const facetCountMaps = facetCounts ? buildFacetCountMaps(facetCounts) : null;

  const totalFiltered = list.meta.total;
  const totalUnfiltered = list.meta.total_unfiltered;
  const totalPages = Math.max(1, Math.ceil(totalFiltered / PAGE_SIZE));
  const offset = list.meta.offset;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const from = totalFiltered === 0 ? 0 : offset + 1;
  const to = offset + list.data.length;
  const sortKey = (typeof params.sort === "string" ? params.sort : DEFAULT_SORT) as keyof typeof SORT_LABELS;
  const sortLabel = SORT_LABELS[sortKey] ?? "recency";
  const geocodedPct =
    counts != null && counts.totalUnfiltered > 0
      ? Math.round((counts.geocodedUnfiltered / counts.totalUnfiltered) * 100)
      : null;
  const yearSpan =
    filterOptions.year_range.min != null && filterOptions.year_range.max != null
      ? `${filterOptions.year_range.min}–${filterOptions.year_range.max}`
      : "—";

  const statItems = [
    { to: totalUnfiltered, label: "Named victims" },
    { to: filterOptions.states.length, label: "States" },
    geocodedPct != null
      ? { to: geocodedPct, suffix: "%", label: "Geocoded" }
      : { display: "—", label: "Geocoded" },
    { display: yearSpan, label: "Incident span" },
  ];

  // Out-of-range clamp via redirect — not silent fallback — so pagination math stays honest.
  if (offset > 0 && offset >= totalFiltered) {
    const { page: _discard, ...withoutPage } = params;
    void _discard;
    redirect(buildListUrl(withoutPage, {}));
  }

  return (
    <PageLoad>
      <div className="mx-auto w-[min(1680px,100%-7vw)] pb-12">
        <div className="pt-8 pb-5">
          <p className="font-mono text-2xs uppercase tracking-eyebrow text-accent">
            Named-victim cold homicides
          </p>
          <h1 className="mt-2 font-display text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
            The case register
          </h1>
          <p className="mt-3 font-mono text-xs tracking-snug text-muted-foreground">
            <span className="text-accent">{totalFiltered.toLocaleString()} records</span> ·{" "}
            {FILTER_DIMENSION_COUNT} filter dimensions · showing {from}–{to} · sorted by {sortLabel}
          </p>
          <div className="mt-6">
            <StatRail items={statItems} />
          </div>
        </div>
        <ListClient
          rows={list.data}
          filterOptions={filterOptions}
          facetCounts={facetCountMaps}
          totalFiltered={totalFiltered}
          totalUnfiltered={totalUnfiltered}
        />
        <ListPagination
          currentPage={currentPage}
          totalPages={totalPages}
          totalFiltered={totalFiltered}
          searchParams={params}
        />
      </div>
    </PageLoad>
  );
}
