import type { Metadata } from "next";
import { cache } from "react";
import { notFound, permanentRedirect } from "next/navigation";
import Image from "next/image";
import { apiFetch, ApiError } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { Breadcrumbs } from "@/components/case/Breadcrumbs";
import { CaseHero } from "@/components/case/CaseHero";
import { VictimCard } from "@/components/case/VictimCard";
import { SubmitTipSection } from "@/components/case/SubmitTipSection";
import { CaseNarrativeWithMO } from "@/components/case-detail/CaseNarrativeWithMO";
import { RelatedCasesPanel } from "@/components/case-detail/RelatedCasesPanel";
import { ExternalReferences } from "@/components/case-detail/ExternalReferences";
import { Block } from "@/components/case-detail/Block";
import { CaseLocationMap } from "@/components/case-detail/CaseLocationMap";
import { PageLoad } from "@/components/chrome/PageLoad";
import { SourceRevealProvider } from "@/components/case-detail/SourceRevealContext";

const PRECISION_LABEL: Readonly<Record<string, string>> = {
  street: "Street",
  landmark: "Landmark",
  zip: "ZIP code",
  county: "County-centroid",
  failed: "Unresolved",
};

/** Whole days since an ISO date, or null when undated/unparseable. */
function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.floor((Date.now() - ms) / 86_400_000));
}

// ISR: render per-case detail pages on first request, cache for 24h.
// Replaces direct-to-main commit bdd4b15's `force-dynamic` cast that bypassed
// prerender entirely — detail pages are the canonical SEO surface and need
// real HTML for crawlers.
export const revalidate = 86400;

type CaseDetailResponse = components["schemas"]["CaseDetailResponse"];

const fetchCase = cache(async (caseId: number): Promise<CaseDetailResponse | null> => {
  try {
    return await apiFetch<CaseDetailResponse>(`/api/v1/cold-cases/${caseId}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string; slug: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const caseId = Number(id);
  if (!Number.isInteger(caseId) || caseId <= 0) return { title: "Not Found" };

  const data = await fetchCase(caseId);
  if (!data) return { title: "Not Found" };

  const location = [data.city, data.state].filter(Boolean).join(", ");
  const year = data.incident_date?.slice(0, 4);
  const title = `${data.case_name}, ${location}${year ? ` (${year})` : ""}`;
  const description = (data.about_text ?? `Cold case record for ${data.case_name} in ${location}.`).slice(0, 160);
  const canonicalUrl = `/cold-cases/${data.case_id}/${data.slug}`;

  return {
    title,
    description,
    alternates: { canonical: canonicalUrl },
    // Social card falls back to the generated app/opengraph-image.tsx (the
    // generic Latent Trace card) — deliberately not a per-case/victim image.
    openGraph: {
      title,
      description,
      url: canonicalUrl,
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ id: string; slug: string }>;
}) {
  const { id, slug } = await params;
  const caseId = Number(id);
  if (!Number.isInteger(caseId) || caseId <= 0) notFound();

  const data = await fetchCase(caseId);
  if (!data) notFound();

  if (slug !== data.slug) {
    permanentRedirect(`/cold-cases/${data.case_id}/${data.slug}`);
  }

  const victimPrimaryName =
    data.victims[0]
      ? [data.victims[0].first_name, data.victims[0].last_name].filter(Boolean).join(" ") || null
      : null;

  const ext = data.extraction;
  const hasVictimExtraction = data.victims.some(
    (v) => v.age_extraction || v.gender_extraction
  );
  const extractionTier: 1 | 2 | null = ext
    ? ext.incident_date || ext.address || hasVictimExtraction
      ? 2
      : 1
    : null;

  const daysOpen = daysSince(data.incident_date);

  const lat = data.latitude != null ? Number(data.latitude) : NaN;
  const lng = data.longitude != null ? Number(data.longitude) : NaN;
  const hasCoords = Number.isFinite(lat) && Number.isFinite(lng);
  const photo = data.photos?.[0];

  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
  const canonicalPath = `/cold-cases/${data.case_id}/${data.slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Latent Trace", item: siteUrl },
          { "@type": "ListItem", position: 2, name: "Cold cases", item: `${siteUrl}/cold-cases` },
          { "@type": "ListItem", position: 3, name: data.case_name, item: `${siteUrl}${canonicalPath}` },
        ],
      },
      {
        "@type": "Article",
        headline: data.case_name,
        url: `${siteUrl}${canonicalPath}`,
        ...(data.about_text ? { description: data.about_text.slice(0, 250) } : {}),
        isPartOf: { "@type": "WebSite", name: "Latent Trace", url: siteUrl },
      },
    ],
  };

  const victimSpans = data.victims.flatMap((v) =>
    [v.age_extraction, v.gender_extraction]
      .filter(
        (f): f is NonNullable<typeof f> =>
          f != null && !f.low_confidence && f.source_start != null && f.source_end != null
      )
      .map((f) => ({ start: f.source_start as number, end: f.source_end as number }))
  );

  return (
    <PageLoad>
      <main className="mx-auto w-[min(1200px,100%-6vw)] pb-16 pt-6">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <Breadcrumbs
          items={[
            { label: "Latent Trace", href: "/" },
            { label: "Cases", href: "/cold-cases" },
            { label: `#${data.source_case_id}` },
          ]}
        />

        <div className="mt-4">
          <CaseHero
            source_case_id={data.source_case_id}
            victim_primary_name={victimPrimaryName}
            case_type={data.case_type}
            incident_date={data.incident_date}
            incident_date_source={data.incident_date_source}
            city={data.city}
            state={data.state}
            latitude={data.latitude}
            longitude={data.longitude}
            daysOpen={daysOpen}
            extractionTier={extractionTier}
          />
        </div>

        <SourceRevealProvider hasNarrative={!!data.about_text}>
        <div className="mt-6 grid grid-cols-1 items-start gap-3.5 lg:grid-cols-3 lg:[grid-auto-flow:row_dense]">
          {/* Victim — cols 1-2 when the map is present, else full width */}
          <Block
            title={data.victims.length === 1 ? "Victim" : "Victims"}
            headingId="victims-heading"
            tag="Extracted"
            className={hasCoords ? "lg:col-span-2" : "lg:col-span-3"}
          >
            <div className="flex flex-col gap-5 sm:flex-row">
                {photo && (
                  <figure className="shrink-0 overflow-hidden rounded-md border border-border bg-inset sm:w-44">
                    {/* Same-origin photo path proxied through Next.js; unoptimized
                        skips Next's image optimizer (no remotePatterns needed). */}
                    <div className="relative aspect-[3/4] w-full">
                      <Image
                        src={`/api/v1/cold-cases/${data.case_id}/photos/${encodeURIComponent(photo.filename)}`}
                        alt={photo.alt_text ?? `Photo for case ${data.case_name}`}
                        fill
                        unoptimized
                        sizes="(max-width: 640px) 100vw, 11rem"
                        className="object-contain"
                      />
                    </div>
                  </figure>
                )}
                <div className="min-w-0 flex-1 space-y-5">
                  {data.victims.map((v, i) => (
                    <div
                      key={v.victim_id}
                      className={i > 0 ? "border-t border-hair pt-5" : undefined}
                    >
                      <VictimCard caseId={data.case_id} {...v} />
                    </div>
                  ))}
                </div>
              </div>
          </Block>

          {/* Recovery location — tall right anchor (col 3, spans 2 rows) */}
          {hasCoords && (
            <Block
              title="Recovery location"
              headingId="recovery-location-heading"
              tag="Geocoded"
              bodyClassName="p-0"
              className="lg:col-start-3 lg:row-span-2"
            >
              <CaseLocationMap lat={lat} lng={lng} precision={data.geocode_precision} />
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5 p-4">
                <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Latitude</dt>
                <dd className="text-right font-mono text-sm tabular-nums text-foreground">
                  {lat.toFixed(4)}
                </dd>
                <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Longitude</dt>
                <dd className="text-right font-mono text-sm tabular-nums text-foreground">
                  {lng.toFixed(4)}
                </dd>
                <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Precision</dt>
                <dd className="text-right text-sm text-foreground">
                  {data.geocode_precision
                    ? (PRECISION_LABEL[data.geocode_precision] ?? data.geocode_precision)
                    : "Unknown"}
                </dd>
                {data.address && (
                  <>
                    <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Address</dt>
                    <dd className="text-right text-sm text-foreground">
                      {data.address}
                      {data.address_source === "tier2" && (
                        <span className="ml-1.5 text-2xs italic text-faint">(extracted)</span>
                      )}
                    </dd>
                  </>
                )}
              </dl>
            </Block>
          )}

          {/* Narrative + MO — main column (CaseNarrativeWithMO renders 2 Blocks) */}
          <div className={(hasCoords ? "lg:col-span-2 lg:col-start-1" : "lg:col-span-3") + " space-y-3.5"}>
            <CaseNarrativeWithMO extraction={data.extraction} aboutText={data.about_text} victimSpans={victimSpans} />
          </div>

          {/* Cases with shared characteristics — main column */}
          <div className={hasCoords ? "lg:col-span-2 lg:col-start-1" : "lg:col-span-3"}>
            <RelatedCasesPanel
              parentExtraction={data.extraction}
              correlations={data.correlations}
              fromCaseId={data.case_id}
            />
          </div>

          {/* Submit a tip — col 3 (under the map) */}
          {data.contact && (
            <div className={hasCoords ? "lg:col-start-3" : "lg:col-span-3"}>
              <SubmitTipSection {...data.contact} />
            </div>
          )}

          {/* External references — full-width bottom strip */}
          <div className="lg:col-span-3">
            <ExternalReferences
              namusCaseId={data.namus_case_id ?? null}
              ncmecCaseId={data.ncmec_case_id ?? null}
              ncicCaseId={data.ncic_case_id ?? null}
            />
          </div>
        </div>
        </SourceRevealProvider>

        <footer className="mt-10 border-t border-hair pt-5 font-mono text-2xs text-faint">
          Case ID {data.case_id} · Data source: Public agency source record
        </footer>
      </main>
    </PageLoad>
  );
}
