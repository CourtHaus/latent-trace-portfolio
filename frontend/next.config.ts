import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

// Content-Security-Policy directive sources, derived from an audit of the
// origins the app actually loads (see SEC-035 in docs/security-backlog.md):
//
//   - PostHog product analytics (src/lib/analytics/client.ts) loads its SDK
//     bundle and ingests events from NEXT_PUBLIC_POSTHOG_HOST (default
//     https://us.i.posthog.com). The *.posthog.com / *.i.posthog.com wildcards
//     cover the US/EU cloud regions and PostHog's asset/reverse-proxy hosts.
//   - Leaflet map tiles (src/components/map/MapLeaflet.tsx) are fetched from
//     CARTO's basemap CDN, served across rotating subdomains
//     ({s}.basemaps.cartocdn.com) — hence the *.basemaps.cartocdn.com wildcard.
//   - Case-detail photos are served through a Next.js rewrite from the
//     same-origin /api/v1/cold-cases/.../photos/... path, so 'self' covers them
//     in production. The configured API origin is allowed in img-src in
//     development only (the direct-origin path) — omitting it in production
//     keeps the backend host out of the public CSP header.
//   - Vercel Speed Insights (src/app/layout.tsx) loads its script and beacons
//     Web Vitals from the same-origin /_vercel/speed-insights/* paths in
//     production (rewritten at Vercel's edge), so 'self' covers it; only the
//     dev debug build is fetched from va.vercel-scripts.com (allowed in dev).
//   - No client-side Google Maps usage was found.
//
// KNOWN CSP WRINKLE: Next.js injects inline <style> tags (and inline styles on
// some elements) during hydration, so style-src needs 'unsafe-inline'. This is
// expected for Next.js App Router and is not worth trying to eliminate with
// nonces/hashes at this stage.
//
// ENFORCING (SEC-F01): this ships as an enforcing `Content-Security-Policy`.
// 'unsafe-eval' is included ONLY in development (the Next.js dev server needs
// it); the production policy omits it. 'unsafe-inline' on script-src remains a
// known Next.js App Router requirement for its bootstrap inline scripts (a
// nonce-based policy would be the next step if we want to drop it).
function originFromUrl(value: string | undefined): string | null {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

const isProduction = process.env.NODE_ENV === "production";
const apiOrigin = originFromUrl(process.env.API_BASE_URL);
const allowedDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const imgSrc = [
  "'self'",
  "data:",
  "blob:",
  "https://*.basemaps.cartocdn.com",
  "https://*.posthog.com",
  // Photos are proxied same-origin via the rewrite below, so 'self' covers
  // them in prod; only dev's direct-origin path needs the API host. Omitting it
  // in production keeps the backend origin out of the public CSP header.
  isProduction ? null : apiOrigin,
].filter(Boolean);

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  // Next.js runtime + PostHog SDK. 'unsafe-inline' covers Next's bootstrap
  // inline scripts; 'unsafe-eval' is required by the Next.js dev server only,
  // so it is omitted from the enforcing production policy.
  // Vercel Speed Insights loads its script same-origin in production
  // (/_vercel/speed-insights/script.js, covered by 'self'); only the dev
  // debug build is fetched from va.vercel-scripts.com, so that host is allowed
  // in development only.
  [
    "script-src 'self' 'unsafe-inline'",
    isProduction ? "" : "'unsafe-eval' https://va.vercel-scripts.com",
    "https://*.posthog.com https://*.i.posthog.com",
  ]
    .filter(Boolean)
    .join(" "),
  // See KNOWN CSP WRINKLE above.
  "style-src 'self' 'unsafe-inline'",
  // CARTO basemap tiles, API-served photos, and inline data/blob images
  // (Leaflet marker icons are rendered as inline SVG/data URIs).
  `img-src ${imgSrc.join(" ")}`,
  "font-src 'self' data:",
  // Backend API (same-origin or external) + PostHog event ingest. Speed
  // Insights beacons same-origin in production (covered by 'self'); the dev
  // debug build talks to va.vercel-scripts.com, allowed in development only.
  [
    "connect-src 'self' https://*.posthog.com https://*.i.posthog.com",
    // Sentry error/trace ingest (src/instrumentation*.ts). The wildcard covers
    // the org-specific regional ingest hosts (*.ingest.{us,de,}.sentry.io).
    // Harmless when Sentry is disabled (no DSN → no beacons are sent).
    "https://*.sentry.io",
    isProduction ? "" : "https://va.vercel-scripts.com",
  ]
    .filter(Boolean)
    .join(" "),
  "worker-src 'self' blob:",
  "manifest-src 'self'",
].join("; ");

const nextConfig: NextConfig = {
  // SEC-F03: don't advertise the framework.
  poweredByHeader: false,
  // Tree-shake icon/util barrel imports (lucide-react) to cut the client bundle
  // and speed up HMR (Vercel best practice: bundle-barrel-imports).
  experimental: { optimizePackageImports: ["lucide-react"] },
  ...(allowedDevOrigins.length > 0 ? { allowedDevOrigins } : {}),
  async rewrites() {
    if (!apiOrigin) return [];

    return [
      {
        source: "/api/v1/cold-cases/:caseId/photos/:filename",
        destination: `${apiOrigin}/api/v1/cold-cases/:caseId/photos/:filename`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          {
            // Enforcing (SEC-F01). See the comment block at the top of this file.
            key: "Content-Security-Policy",
            value: contentSecurityPolicy,
          },
        ],
      },
    ];
  },
};

// Sentry build-time wrapping: injects release info and (when SENTRY_AUTH_TOKEN
// + org/project are set) uploads source maps. With those env vars unset this is
// a no-op and the build proceeds normally — runtime error capture still works,
// just without symbolicated stack traces.
export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  // Quiet unless running in CI.
  silent: !process.env.CI,
});
