"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { initAnalytics, track } from "@/lib/analytics/client";

function PageviewTracker() {
  const pathname = usePathname();
  // Subscribed for completeness so re-renders fire on querystring nav,
  // but we intentionally do NOT include the querystring in the tracked path.
  useSearchParams();

  // Both effects live here (not split across components) so initAnalytics
  // fires BEFORE track on mount — React runs effects in declaration order
  // within a single component. If init were in the outer component, the
  // inner track() would fire first (children before parents) and hit the
  // !initialized guard, dropping the initial page_viewed event.
  useEffect(() => {
    initAnalytics();
  }, []);

  useEffect(() => {
    if (!pathname) return;
    track("page_viewed", { path: pathname });
  }, [pathname]);

  return null;
}

export function AnalyticsProvider({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Suspense fallback={null}>
        <PageviewTracker />
      </Suspense>
      {children}
    </>
  );
}
