import type { MetadataRoute } from "next";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

type ColdCaseListResponse = components["schemas"]["ColdCaseListResponse"];
type ColdCaseListItem = components["schemas"]["ColdCaseListItem"];

export const revalidate = 86400; // 24h ISR

const PAGE_SIZE = 1000;
// Safety cap so a bad response can never spin this unbounded. 50k >> the
// foreseeable corpus; bump if it ever approaches this.
const MAX_PAGES = 50;
// Each page is retried before giving up: a single transient API blip (e.g. a
// Cloud Run cold start during a deploy) must not abort the whole production
// build. Short linear backoff is plenty for a warming instance.
const PAGE_RETRIES = 3;
const RETRY_BASE_MS = 500;

async function fetchPage(page: number): Promise<ColdCaseListItem[] | null> {
  for (let attempt = 1; attempt <= PAGE_RETRIES; attempt++) {
    try {
      const data = await apiFetch<ColdCaseListResponse>(
        `/api/v1/cold-cases?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}&sort=incident_date_desc`,
        // Opt into the Data Cache (apiFetch defaults to no-store): otherwise a
        // sitemap regen walks every page uncached and can hit the list
        // endpoint's rate limit under crawler traffic. Matches this route's
        // ISR window.
        { next: { revalidate } },
      );
      return data.data;
    } catch (err) {
      if (attempt === PAGE_RETRIES) {
        console.error(`[sitemap] page ${page} failed after ${PAGE_RETRIES} attempts:`, err);
        return null;
      }
      await new Promise((resolve) => setTimeout(resolve, RETRY_BASE_MS * attempt));
    }
  }
  return null;
}

/**
 * Detail pages are the canonical SEO surface, so the sitemap must list ALL of
 * them, not just the first page. Walk the paginated list endpoint until a short
 * page (fewer than PAGE_SIZE rows) signals the end.
 *
 * Resilience: each page is retried, and if one still fails we degrade to a
 * partial sitemap (the pages collected so far) rather than throwing. A failed
 * production build blocks every change; a briefly-incomplete sitemap does not
 * deindex anything and is restored on the next regen/deploy. The first page is
 * the exception: if we cannot get a single case (API genuinely down), we throw,
 * because shipping a static-only sitemap would silently drop the entire case
 * corpus from search.
 */
async function fetchAllCases(): Promise<ColdCaseListItem[]> {
  const rows: ColdCaseListItem[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const pageRows = await fetchPage(page);
    if (pageRows === null) {
      if (page === 0) {
        throw new Error(
          "[sitemap] list endpoint unreachable on the first page; refusing to " +
            "emit a case-less sitemap.",
        );
      }
      console.error(
        `[sitemap] giving up at page ${page}; emitting ${rows.length} case URLs (partial).`,
      );
      break;
    }
    rows.push(...pageRows);
    if (pageRows.length < PAGE_SIZE) break;
  }
  return rows;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const cases = await fetchAllCases();
  const base = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

  return [
    { url: `${base}/`, changeFrequency: "monthly" as const, priority: 0.5 },
    { url: `${base}/cold-cases`, changeFrequency: "daily" as const, priority: 0.8 },
    { url: `${base}/cold-cases/map`, changeFrequency: "monthly" as const, priority: 0.7 },
    { url: `${base}/methodology`, changeFrequency: "monthly" as const, priority: 0.6 },
    { url: `${base}/about`, changeFrequency: "monthly" as const, priority: 0.4 },
    { url: `${base}/privacy`, changeFrequency: "yearly" as const, priority: 0.3 },
    { url: `${base}/terms`, changeFrequency: "yearly" as const, priority: 0.3 },
    ...cases.map((row) => ({
      url: `${base}/cold-cases/${row.case_id}/${row.slug}`,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
