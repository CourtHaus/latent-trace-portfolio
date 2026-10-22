import type { Metadata } from "next";
import { PrivacyOptOutControl } from "./PrivacyOptOutControl";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What Latent Trace collects, what it doesn't, and how to opt out of analytics.",
  alternates: { canonical: "/privacy" },
  openGraph: {
    title: "Privacy · Latent Trace",
    description: "What Latent Trace collects, what it doesn't, and how to opt out.",
    url: "/privacy",
  },
};

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12 space-y-6 text-foreground">
      <h1 className="text-3xl font-semibold tracking-tight">Privacy</h1>

      <p className="text-base leading-relaxed text-foreground">
        Latent Trace is a public-facing research tool. We try to collect as little
        data about visitors as we technically can while still learning whether
        the product is useful. This page explains product analytics, operational services, and how to
        opt out of PostHog analytics.
      </p>

      <h2 className="text-xl font-semibold mt-8">What we collect</h2>
      <p className="text-base leading-relaxed text-foreground">
        We use <a href="https://posthog.com" target="_blank" rel="noreferrer" className="text-accent hover:underline">PostHog</a>{" "}
        (PostHog Cloud, US instance) to capture a small number of explicit
        product events. We do not use cookies for analytics, and we do not
        identify individual visitors. A short anonymous identifier is stored
        in your browser&apos;s <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">localStorage</code> so we can measure aggregate
        navigation paths across visits until browser storage is cleared (e.g., &ldquo;what fraction of visitors
        who reach a case detail also click through to another case&rdquo;); this identifier
        is not linked to any personal information and is never sent to any
        third party other than PostHog.
      </p>

      <p className="text-base leading-relaxed text-foreground">The full list of events:</p>
      <ul className="space-y-2 text-base leading-relaxed text-muted-foreground list-disc list-inside">
        <li><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">page_viewed</code>: which public route patterns get visited (case names and IDs are removed from paths). Property: <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">path</code> (no querystring).</li>
        <li><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">map_interacted</code>: that the map was panned/zoomed or a marker clicked. Properties: <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">interaction_type</code>; for marker clicks, <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">case_id</code>.</li>
        <li><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">filter_applied</code>: that a filter was changed. Property: <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">filter_key</code> (which filter). <strong className="font-medium text-foreground">Filter values are never sent</strong>. We don&apos;t record what demographics or attributes you searched for.</li>
        <li><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">filter_cleared</code>: that filters were cleared. Property: <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">scope</code>.</li>
        <li><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">related_case_clicked</code>: that a case in the &ldquo;cases with shared characteristics&rdquo; panel was clicked through. Properties: source case ID, destination case ID, rank in list.</li>
        <li><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">source_revealed</code>: that the click-to-reveal source-text affordance was used. Property: which field.</li>
        <li><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">analytics_opted_out</code>: when a visitor opts out (one-time).</li>
      </ul>

      <h2 className="text-xl font-semibold mt-8">PostHog collection limits</h2>
      <ul className="space-y-2 text-base leading-relaxed text-muted-foreground list-disc list-inside">
        <li>No cookies set for analytics (PostHog is configured for localStorage-only persistence).</li>
        <li>Product events omit IP fields from the browser payload and disable geographic enrichment. Receiving services still see your network IP address; retention depends on provider settings.</li>
        <li>No automatic capture of clicks, keystrokes, form inputs, or page contents.</li>
        <li>No session replay or screen recording.</li>
        <li>No filter <em>values</em> (we record that you used the weapon filter, not which weapon).</li>
        <li>No search query text in PostHog events; URL and referrer metadata are removed before events are sent.</li>
        <li>No third-party advertising networks. No Google Analytics. No Facebook Pixel. Nothing of that family.</li>
      </ul>

      <h2 className="text-xl font-semibold mt-8">Hosting, diagnostics, and maps</h2>
      <p className="text-base leading-relaxed text-foreground">
        Vercel hosts the frontend, Google Cloud Run serves the API, and Supabase
        supports data storage and operator authentication. These services
        receive network requests and may process connection and diagnostic
        information, including IP addresses. Operator sign-in uses authentication
        cookies separately from product analytics.
      </p>
      <p className="text-base leading-relaxed text-foreground">
        Vercel Speed Insights measures page performance and associated route,
        browser, and device information. When enabled, Sentry receives error
        diagnostics with default personal-information collection disabled.
        Map backgrounds request tiles from CARTO, which receives your network
        request and the requested map area. These operational services are
        separate from PostHog; the opt-out below controls PostHog events only.
      </p>

      <h2 className="text-xl font-semibold mt-8">Why we collect anything at all</h2>
      <p className="text-base leading-relaxed text-foreground">
        The questions we&apos;re trying to answer: does anyone reach the methodology
        page? Does the &ldquo;cases with shared characteristics&rdquo; panel get used? Where do users
        drop off in the filter sidebar? Without this data, we&apos;d be guessing at
        every product decision, which means building features that may not
        help.
      </p>

      <h2 className="text-xl font-semibold mt-8">Opt out</h2>
      <p className="text-base leading-relaxed text-foreground">
        To stop PostHog product analytics in this browser, click the button below. Your choice
        is stored in your browser&apos;s <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">localStorage</code> (no cookie involved) and persists across
        visits on this device.
      </p>

      <PrivacyOptOutControl />

      <h2 className="text-xl font-semibold mt-8">Removing your data</h2>
      <p className="text-base leading-relaxed text-foreground">
        We do not ask analytics visitors to identify themselves, so we may not
        be able to associate a request with specific events. Contact us to
        discuss access or deletion requests and the information needed to
        evaluate them. Do not send passwords, access tokens, or private case
        details in an initial request.
      </p>

      <h2 className="text-xl font-semibold mt-8">Contact</h2>
      <p className="text-base leading-relaxed text-foreground">
        For privacy questions, data removal of personally-identifying content
        published on the site (e.g., a case detail page about you or a family
        member), or anything else about how this site uses data, email{" "}
        <a href="mailto:courtney@latenttrace.org" className="text-accent hover:underline">courtney@latenttrace.org</a>.
      </p>

      <p className="text-sm text-muted-foreground">
        Last updated: 2026-10-22
      </p>
    </main>
  );
}
