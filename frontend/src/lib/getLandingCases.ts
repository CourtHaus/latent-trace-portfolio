import { cache } from "react";
import { apiFetch, READ_REVALIDATE_SECONDS } from "@/lib/api";
import type { components } from "@/lib/api-types";

type ListResponse = components["schemas"]["ColdCaseListResponse"];
export type LandingCase = components["schemas"]["ColdCaseListItem"];

/**
 * A few real recent cases for the landing's §02 ledger mini-preview — so it
 * shows actual records (ID · subject · year) rather than empty placeholders.
 */
export const getLandingCases = cache(async (): Promise<LandingCase[]> => {
  const r = await apiFetch<ListResponse>(
    "/api/v1/cold-cases?limit=4&sort=incident_date_desc",
    { next: { revalidate: READ_REVALIDATE_SECONDS } },
  );
  return r.data;
});

/** Resilient variant: returns [] instead of throwing when the fetch fails, so
 *  the landing's recent-cases preview degrades gracefully rather than failing
 *  the whole page on a transient API blip (e.g. a Cloud Run cold-start 500). */
export const getLandingCasesOrEmpty = cache(async (): Promise<LandingCase[]> => {
  try {
    return await getLandingCases();
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(`[getLandingCasesOrEmpty] fetch failed: ${String(err)}`);
    }
    return [];
  }
});
