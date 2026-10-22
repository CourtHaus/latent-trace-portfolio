import posthog, { type CaptureResult } from "posthog-js";

const OPT_OUT_KEY = "cs_analytics_optout";

// Module-level state so track() doesn't depend on posthog's internal
// __loaded property (private API, may change between SDK versions).
let initialized = false;

const eventFields: Record<string, readonly string[]> = {
  page_viewed: ["path"],
  map_interacted: ["interaction_type", "case_id"],
  filter_applied: ["filter_key"],
  filter_cleared: ["scope"],
  related_case_clicked: ["from_case_id", "to_case_id", "rank"],
  source_revealed: ["field"],
  analytics_opted_out: [],
};

const publicRoutes = new Set([
  "/", "/cold-cases", "/cold-cases/map", "/methodology", "/about",
  "/privacy", "/terms",
]);

/** Applied after SDK enrichment, so automatic URL/referrer properties cannot leak queries. */
export function sanitizeAnalyticsEvent(event: CaptureResult | null): CaptureResult | null {
  if (!event || !Object.hasOwn(eventFields, event.event)) return null;
  const properties: CaptureResult["properties"] = {
    $process_person_profile: false,
    $geoip_disable: true,
  };
  // Preserve ingestion routing and anonymous identity. The project token is
  // intentionally public; removing it makes the SDK reject every event.
  for (const key of ["token", "distinct_id"]) {
    if (typeof event.properties[key] === "string") properties[key] = event.properties[key];
  }
  for (const key of eventFields[event.event]!) {
    const value: unknown = event.properties[key];
    if (typeof value === "string" || typeof value === "number") properties[key] = value;
  }
  if (event.event === "page_viewed") {
    const path = typeof properties.path === "string" ? properties.path.split(/[?#]/)[0]! : "";
    if (path.startsWith("/admin") || path.startsWith("/auth")) return null;
    properties.path = publicRoutes.has(path)
      ? path
      : /^\/cold-cases\/[^/]+\/[^/]+\/?$/.test(path)
        ? "/cold-cases/[id]/[slug]"
        : "/other";
  }
  // Do not spread the input: top-level $set/$set_once can contain initial URLs.
  return { event: event.event, uuid: event.uuid, timestamp: event.timestamp, properties };
}

function isOptedOut(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(OPT_OUT_KEY) === "true";
  } catch {
    return false;
  }
}

export function initAnalytics(): void {
  if (initialized) return;
  if (typeof window === "undefined") return;
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (!key) return;
  if (isOptedOut()) return;

  const host = process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com";

  posthog.init(key, {
    api_host: host,
    autocapture: false,
    capture_pageview: false,
    capture_pageleave: false,
    capture_dead_clicks: false,
    capture_exceptions: false,
    disable_session_recording: true,
    disable_surveys: true,
    save_referrer: false,
    save_campaign_params: false,
    before_send: sanitizeAnalyticsEvent,
    // IP retention is controlled by the PostHog project's Discard client IP
    // data setting; the deprecated SDK `ip` option does not enforce it.
    person_profiles: "identified_only",
    // CRITICAL: default is 'localStorage+cookie'. We explicitly drop cookies
    // to match the no-cookies privacy claim. localStorage still holds an
    // anonymous distinct_id which can persist across visits until cleared.
    persistence: "localStorage",
  });

  initialized = true;
}

export type AnalyticsEvent =
  | "page_viewed"
  | "map_interacted"
  | "filter_applied"
  | "filter_cleared"
  | "related_case_clicked"
  | "source_revealed"
  | "analytics_opted_out";

export function track(event: AnalyticsEvent, properties?: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  if (!initialized) return;
  // Belt-and-suspenders: re-check opt-out at every track call, not just at
  // init. Covers the case where a user opts out in another tab and
  // localStorage is updated before posthog's internal state syncs.
  if (isOptedOut()) return;
  try {
    posthog.capture(event, properties);
  } catch {
    // Analytics must never crash the app. Swallow silently.
  }
}

export function optOut(): void {
  if (typeof window === "undefined") return;
  // ORDER MATTERS:
  //   1. Capture the opt-out event FIRST while posthog still accepts events.
  //   2. THEN persist the localStorage flag so future tabs / track() calls
  //      see the opt-out state.
  //   3. THEN tell posthog to stop capturing (this drops subsequent events).
  // If we reversed (2) and (3) we'd lose the analytics_opted_out event,
  // because opt_out_capturing() makes posthog drop pending captures.
  track("analytics_opted_out");
  try {
    window.localStorage.setItem(OPT_OUT_KEY, "true");
  } catch {
    // ignore quota errors — best-effort
  }
  if (initialized) {
    posthog.opt_out_capturing();
  }
}

export function isAnalyticsEnabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_POSTHOG_KEY) && !isOptedOut();
}
