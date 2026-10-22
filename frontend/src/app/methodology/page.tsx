import type { Metadata } from "next";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { CoverageMap } from "@/components/methodology/CoverageMap";
import {
  CompletenessMatrix,
  CompletenessLegend,
} from "@/components/methodology/CompletenessMatrix";
import { StateCoverageTable } from "@/components/methodology/StateCoverageTable";
import { getFilterOptions } from "@/lib/getFilterOptions";
import { getDatasetCounts } from "@/lib/getDatasetCounts";
import { getSourcesSummary } from "@/lib/getSourcesSummary";
import { getCorrelationWeights } from "@/lib/getCorrelationWeights";
import { MD_COVERAGE } from "@/lib/methodology/sourceMetadata";

export const metadata: Metadata = {
  title: "Methodology",
  description:
    "How Latent Trace turns public records into research-grade case data: provenance, extraction, correlation, and the limits we know about.",
  alternates: { canonical: "/methodology" },
  openGraph: {
    title: "Methodology · Latent Trace",
    description: "How Latent Trace turns public records into research-grade case data.",
    url: "/methodology",
  },
};

const SECTIONS = [
  { mark: "01", id: "preamble", label: "Preamble" },
  { mark: "02", id: "data-sources", label: "Data sources" },
  { mark: "03", id: "modus-operandi", label: "Modus operandi" },
  { mark: "04", id: "correlation", label: "Correlation" },
  { mark: "05", id: "geocoding-precision", label: "Geocoding precision" },
  { mark: "06", id: "bias", label: "Bias & selection effects" },
  { mark: "07", id: "limits", label: "Limits & open questions" },
  { mark: "08", id: "citation", label: "Citation & reuse" },
  { mark: "09", id: "revision-history", label: "Revision history" },
] as const;

/**
 * Curated methodology revision log — substantive changes to how the data is
 * built or documented, not every code commit. Newest first. Add an entry
 * when a change here would alter how a careful reader interprets the data.
 */
const METHODOLOGY_REVISIONS = [
  {
    date: "2026-05-16",
    note: "Methodology page rebuilt: coverage map, per-source field-completeness matrix, dedicated bias & selection-effects section, and grounded correlation weighting.",
  },
  {
    date: "2026-05-14",
    note: "New Hampshire DOJ ingested; suspicious_death added as a distinct case type for deaths not yet ruled homicides.",
  },
  {
    date: "2026-05-12",
    note: "Google geocoding tier added between Census and ZIP-centroid fallback; four-tier precision visualization introduced.",
  },
  {
    date: "2026-04-21",
    note: "Initial methodology published alongside the first security-audited dataset.",
  },
] as const;


interface SectionHeaderProps {
  mark: string;
  id: string;
  eyebrow: string;
  title: string;
  blurb?: string;
  rev?: string;
}

function SectionHeader({ mark, id, eyebrow, title, blurb, rev }: SectionHeaderProps) {
  return (
    <header id={id} className="scroll-mt-24 mb-10">
      <div className="flex items-baseline justify-between gap-4 mb-4 pb-3 border-b border-border">
        <div className="flex items-baseline gap-3 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
          <span className="text-accent font-medium">§ {mark}</span>
          <span>{eyebrow}</span>
        </div>
        {rev && (
          <span className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground/80">
            {rev}
          </span>
        )}
      </div>
      <h2 className="text-4xl sm:text-[42px] font-medium leading-none tracking-tight text-foreground">
        {title}
      </h2>
      {blurb && (
        <p className="mt-4 max-w-prose text-base leading-relaxed text-muted-foreground">
          {blurb}
        </p>
      )}
    </header>
  );
}

interface StatProps {
  eyebrow: string;
  value: string;
  unit?: string;
  body: string;
}

function StatCard({ eyebrow, value, unit, body }: StatProps) {
  return (
    <Card data-slot="stat-card">
      <CardContent className="p-6">
        <div className="mb-2.5 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
          {eyebrow}
        </div>
        <div className="mb-2 text-3xl font-medium leading-none tracking-tight text-foreground">
          {value}
          {unit && (
            <span className="ml-1 text-base font-normal text-muted-foreground">
              {unit}
            </span>
          )}
        </div>
        <p className="text-xs leading-normal text-muted-foreground">
          {body}
        </p>
      </CardContent>
    </Card>
  );
}

/** A human label for each internal dimension key in the worked-example table. */
const DIMENSION_LABELS: Record<string, string> = {
  weapon: "Weapon",
  location_type: "Location type",
  victim_gender: "Victim gender",
  victim_race: "Victim race",
  victim_age: "Victim age",
};

interface ExampleRowProps {
  dimension: string;
  value: string;
  bits: number;
  rarity: "common" | "rare";
}

function ExampleRow({ dimension, value, bits, rarity }: ExampleRowProps) {
  const isRare = rarity === "rare";
  return (
    <div className="grid grid-cols-[1.2fr_1.4fr_88px_70px] items-baseline gap-3 px-5 py-3 border-b border-border last:border-b-0 text-sm">
      <div className="text-foreground font-medium">
        {DIMENSION_LABELS[dimension] ?? dimension}
      </div>
      <div className="text-muted-foreground">{value}</div>
      <div>
        <span
          className={`font-mono text-2xs uppercase tracking-eyebrow ${
            isRare ? "text-accent font-medium" : "text-faint"
          }`}
        >
          {isRare ? "rare" : "common"}
        </span>
      </div>
      <div className="text-right font-mono tabular-nums text-foreground">
        {bits.toFixed(2)}
      </div>
    </div>
  );
}

export default async function MethodologyPage() {
  const [filterOptions, counts, sourcesSummary, weights] = await Promise.all([
    getFilterOptions(),
    getDatasetCounts(),
    getSourcesSummary(),
    getCorrelationWeights(),
  ]);

  const yearMin = filterOptions.year_range.min ?? 1961;
  const yearMax = filterOptions.year_range.max ?? new Date().getFullYear();
  const sources = sourcesSummary.data;
  const sourceCount = sources.length;
  const coveredStates = Array.from(
    new Set(sources.map((s) => s.state).filter((s): s is string => s != null)),
  );
  // MD has sub-state coverage (6 of 24 counties) so it shows up as partial in
  // addition to "covered" — keeps the at-a-glance map honest.
  const partialStates =
    coveredStates.includes("MD") &&
    MD_COVERAGE.covered.length <
      MD_COVERAGE.covered.length +
        MD_COVERAGE.noRoster.length +
        MD_COVERAGE.stateHandled.length
      ? ["MD"]
      : [];
  const stateCount = coveredStates.length;
  const geocodedPercent =
    counts.totalUnfiltered > 0
      ? ((counts.geocodedUnfiltered / counts.totalUnfiltered) * 100).toFixed(1)
      : "0.0";

  // Concrete revision signal for the hero eyebrow — beats a vague
  // "working documentation" hedge. Falls back to the dataset version
  // string alone if last_ingested is null.
  const lastIngested = filterOptions.dataset.last_ingested;
  const datasetDate = lastIngested
    ? new Date(lastIngested).toLocaleDateString("en-US", {
        month: "long",
        year: "numeric",
      })
    : null;
  // ISO date for the §07 suggested citation.
  const citationRevision = lastIngested
    ? new Date(lastIngested).toISOString().slice(0, 10)
    : null;
  // Public origin for the citation URL. Set NEXT_PUBLIC_SITE_URL at deploy
  // (see docs/deploy/runbook.md); in dev it falls back to localhost.
  const siteUrl = (
    process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"
  ).replace(/\/$/, "");

  return (
    <main>
      {/* ─────────────── HERO ─────────────── */}
      <section className="px-8 pt-20 pb-10 sm:px-12 sm:pt-30">
        <div className="mx-auto max-w-reading">
          <div className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground mb-5">
            METHODOLOGY · DATASET {filterOptions.dataset.version}
            {datasetDate ? ` · UPDATED ${datasetDate}` : ""}
          </div>
          <h1 className="text-[52px] sm:text-[72px] leading-none font-medium tracking-tight text-foreground mb-6">
            How the data is made.
          </h1>
          <p className="max-w-prose text-lg leading-relaxed text-muted-foreground">
            Latent Trace aggregates cold-case records from official law-enforcement
            sources, normalizes them into a research-grade schema, and runs
            local LLM extraction over the narrative text to surface structured
            modus-operandi fields. Every algorithm is documented here, with
            explicit transparency about confidence, provenance, and limits.
          </p>
          <p className="mt-5 max-w-prose text-base leading-relaxed text-muted-foreground/80">
            Nothing here is a suspect identification. Every correlation and
            extracted field is a lead for human review, never a conclusion.
          </p>
        </div>
      </section>

      {/* ─────────────── STAT ROW ─────────────── */}
      <section className="px-8 sm:px-12 pb-20">
        <div className="mx-auto max-w-reading">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              eyebrow="Cases indexed"
              value={counts.totalUnfiltered.toLocaleString()}
              body={`${yearMin}–${yearMax}, across ${sourceCount} active source${sourceCount === 1 ? "" : "s"}.`}
            />
            <StatCard
              eyebrow="Geocoded coverage"
              value={geocodedPercent}
              unit="%"
              body={`${counts.geocodedUnfiltered.toLocaleString()} cases plot to coordinates; the remainder are pending geographic resolution.`}
            />
            <StatCard
              eyebrow="Extraction precision"
              value="96.3 / 100"
              unit="%"
              body="Weapon and location-type classification, re-measured on qwen3:14b against the hand-labeled validation set."
            />
            <StatCard
              eyebrow="Default extraction"
              value="Local"
              unit="Ollama"
              body="Narrative extraction uses Qwen3:14b on local infrastructure. Geocoding, hosting, and optional source tooling use separate services."
            />
          </div>
        </div>
      </section>

      {/* ─────────────── TOC ─────────────── */}
      <section className="px-8 sm:px-12 pb-16">
        <div className="mx-auto max-w-reading">
          <div className="mb-3 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
            Contents
          </div>
          <ol className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1.5">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <Link
                  href={`#${s.id}`}
                  className="group flex items-baseline gap-3 py-1.5 text-sm text-foreground hover:text-accent transition-colors"
                >
                  <span className="font-mono text-2xs tracking-eyebrow text-muted-foreground group-hover:text-accent transition-colors w-[28px]">
                    § {s.mark}
                  </span>
                  <span>{s.label}</span>
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ─────────────── § 01 PREAMBLE ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="01"
            id="preamble"
            eyebrow="Preamble"
            title="Who this is for, and what we promise."
            rev="standing"
          />
          <div className="max-w-prose space-y-5 text-base leading-relaxed text-foreground">
            <p>
              Latent Trace is a public-facing analytics platform for serious
              non-professional investigators: citizen detectives, journalists,
              students, data scientists, and genetic genealogists working
              cases that law-enforcement tools wouldn&apos;t give them access
              to. The promise is simple: every transformation we apply to a
              case is documented, every extracted field carries a verifiable
              link back to its source phrase, and every limitation we know
              about is surfaced rather than buried.
            </p>
            <p>
              The framing matters. Latent Trace surfaces structure from a corpus
              too large to read by hand, but structure is not a verdict. A
              shared weapon and a 30-mile radius make two cases{" "}
              <em>worth comparing</em>, not the same case. The methodology
              below exists so a careful reader can audit the substrate of any
              claim the interface makes, and decide for themselves what the
              signal is worth.
            </p>
          </div>
        </div>
      </section>

      {/* ─────────────── § 02 DATA SOURCES ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="02"
            id="data-sources"
            eyebrow="Data sources"
            title="Coverage and per-source field completeness."
            blurb="Latent Trace ingests cold-case data from official law-enforcement sources only. Coverage today spans the states colored below; expand any state for the underlying sources, refresh cadence, geocoding strategy, and the caveats that travel with each one."
            rev={`${sourceCount} active`}
          />

          {/* Coverage map */}
          <div className="mb-6 rounded-md border border-border bg-card p-5">
            <div className="mb-3 flex items-baseline justify-between gap-3 flex-wrap">
              <h3 className="font-mono text-2xs uppercase tracking-eyebrow text-accent">
                Coverage at a glance
              </h3>
              <span className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                {stateCount} state{stateCount === 1 ? "" : "s"} ·{" "}
                {sourceCount} source{sourceCount === 1 ? "" : "s"} ·{" "}
                {counts.totalUnfiltered.toLocaleString()} cases
              </span>
            </div>
            <CoverageMap
              coveredStates={coveredStates}
              partialStates={partialStates}
            />
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm bg-accent/70" />
                Covered
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm bg-accent/30" />
                Partial (county-level)
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm bg-muted/40 border border-border" />
                Not yet
              </span>
            </div>
          </div>

          {/* State table — expandable rows */}
          <StateCoverageTable sources={sources} />

          {/* Completeness matrix */}
          <div className="mt-10 mb-3 flex items-baseline justify-between gap-3 flex-wrap">
            <h3 className="text-lg font-medium tracking-snug text-foreground">
              Per-source field completeness
            </h3>
            <span className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
              what each source provides
            </span>
          </div>
          <CompletenessMatrix sources={sources} />
          <CompletenessLegend />
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            Cells where a field is{" "}
            <span className="text-foreground font-medium">structural</span>{" "}
            (source-provided) carry the strongest provenance. Cells marked{" "}
            <span className="text-accent font-medium">LLM-extracted</span>{" "}
            point at a verbatim source phrase via the case detail page&apos;s{" "}
            <em>Source ▸</em> reveal. Cells marked{" "}
            <span className="text-destructive/80 font-medium">not in source</span>{" "}
            are honest absences. Latent Trace does not infer demographics from
            photographs or names.
          </p>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            Victim race is recorded exactly as the source agency reported it and
            shown that way on each case. For filtering only, the many source
            spellings of one category (Black, BLACK or AFRICAN AMERICAN, African
            American) are grouped into standard FBI/NIBRS categories so the filter
            does not fragment; the original value is never overwritten. Hispanic
            or Latino is an ethnicity rather than a race, but some agencies record
            it in the race field, so it is carried as a category here. This is a
            fixed grouping of source-provided values, not inference.
          </p>
        </div>
      </section>

      {/* ─────────────── § 03 MODUS OPERANDI ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="03"
            id="modus-operandi"
            eyebrow="Modus operandi extraction"
            title="What gets pulled from each narrative."
            blurb="Local LLM extraction surfaces structured modus-operandi fields from case narratives. How much runs depends on the source: weapon and location type are extracted wherever a narrative exists; dates, addresses, and demographics are extracted only where the source publishes prose instead of structured fields, and sources that already publish structured records need no extraction at all. The §02 completeness matrix shows exactly which fields are extracted per source."
            rev="Tier 1 + Tier 2"
          />

          <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-8 mb-10">
            <div className="space-y-5 text-base leading-relaxed text-foreground">
              <p>
                The model that produces these classifications is{" "}
                <strong className="font-medium">Qwen3:14b</strong>, an
                open-weights model run locally on Latent Trace infrastructure.
                No case data is sent to third-party AI services. Privacy and
                local execution are the trust signals that matter for
                investigative work; running everything on local hardware
                means a case you research here doesn&apos;t leak to OpenAI,
                Anthropic, or any other vendor.
              </p>
              <p>
                Where a source already publishes a field as structured data (
                Colorado, Utah, and Ohio ship victim demographics directly;
                Wyoming ships weapon and scene type too), Latent Trace trusts the
                source value and does not re-derive it with the model. Extraction
                fills gaps; it never overrides first-party data.
              </p>
              <p>
                Each classification carries one of two confidence states,
                plus a separate <em>unknown</em> for cases where the
                narrative simply doesn&apos;t say.
              </p>
            </div>

            <div className="rounded-md border border-accent/40 bg-accent/5 p-5">
              <div className="mb-3 font-mono text-2xs uppercase tracking-eyebrow text-accent">
                Locality
              </div>
              <ul className="space-y-2.5 text-sm text-muted-foreground">
                <li className="flex items-baseline gap-2">
                  <span className="font-mono text-accent">·</span>
                  <span>Model: Qwen3:14b (open weights)</span>
                </li>
                <li className="flex items-baseline gap-2">
                  <span className="font-mono text-accent">·</span>
                  <span>Inference: local hardware only</span>
                </li>
                <li className="flex items-baseline gap-2">
                  <span className="font-mono text-accent">·</span>
                  <span>Egress: zero, no third-party API calls</span>
                </li>
                <li className="flex items-baseline gap-2">
                  <span className="font-mono text-accent">·</span>
                  <span>Determinism: temperature pinned to 0.0</span>
                </li>
              </ul>
            </div>
          </div>

          <h3 className="text-lg font-medium tracking-snug text-foreground mb-4">
            Confidence states
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-10">
            <Card>
              <CardContent className="p-5">
                <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-accent">
                  Confident
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Classification produced and anchored to a verbatim phrase
                  in the narrative. The detail page&apos;s{" "}
                  <em>Source ▸</em> button reveals the exact span.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                  Uncertain
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Classification stands but the model paraphrased
                  (&ldquo;at her place&rdquo; vs &ldquo;at her
                  apartment&rdquo;). The audit trail does not.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground/70">
                  Unknown
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  The narrative doesn&apos;t specify the attribute. Excluded
                  from scoring; surfaced as &ldquo;not provided&rdquo; on
                  the detail page.
                </p>
              </CardContent>
            </Card>
          </div>

          <h3 className="text-lg font-medium tracking-snug text-foreground mb-4">
            Source-span anchoring · live example
          </h3>
          <Card>
            <CardContent className="p-7">
              <p className="text-base leading-relaxed text-foreground mb-5">
                On October 10, 2010 at approximately 9:30 p.m., officers
                found the victim suffering from a{" "}
                <mark className="bg-accent/20 text-foreground border-b-[1.5px] border-accent px-1 rounded-sm">
                  gunshot wound
                </mark>{" "}
                on the ground. He was taken to the hospital where he later
                died of his injuries.
              </p>
              <div className="grid grid-cols-[110px_1fr] gap-y-1.5 gap-x-4 text-xs font-mono pt-4 border-t border-border">
                <span className="text-muted-foreground uppercase tracking-eyebrow">
                  extracted
                </span>
                <span className="text-foreground">weapon = firearm</span>
                <span className="text-muted-foreground uppercase tracking-eyebrow">
                  raw phrase
                </span>
                <span className="text-foreground">&ldquo;gunshot wound&rdquo;</span>
                <span className="text-muted-foreground uppercase tracking-eyebrow">
                  span
                </span>
                <span className="text-foreground">chars 92–105</span>
                <span className="text-muted-foreground uppercase tracking-eyebrow">
                  confidence
                </span>
                <span className="text-accent">confident · anchored</span>
              </div>
            </CardContent>
          </Card>

          <h3 className="mt-10 text-lg font-medium tracking-snug text-foreground mb-4">
            Validation
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <StatCard
              eyebrow="Weapon · precision / recall"
              value="96.3 / 96.3"
              unit="%"
              body="Hand-labeled validation set, re-scored on every prompt or model change (current: qwen3:14b)."
            />
            <StatCard
              eyebrow="Location type · P/R"
              value="100 / 100"
              unit="%"
              body="Same validation set. The earlier address-as-geolocation misses (a street address pulling an outdoor body toward residence) were closed by the tier-1 v2 prompt fix."
            />
            <StatCard
              eyebrow="Uncertain rate · location"
              value="17.9"
              unit="%"
              body="Defensible classification, paraphrased anchor. Known v1 limitation; will narrow with prompt iteration."
            />
          </div>

          <div className="mt-6 rounded-md border border-border bg-muted/40 p-5">
            <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
              Audit
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">
              For data-quality audits, the table{" "}
              <code className="font-mono text-xs bg-background px-1.5 py-0.5 rounded border border-border">
                cold_case.case_extractions_current
              </code>{" "}
              is the authoritative latest extraction per case. A{" "}
              <code className="font-mono text-xs bg-background px-1.5 py-0.5 rounded border border-border">
                LEFT JOIN
              </code>{" "}
              against{" "}
              <code className="font-mono text-xs bg-background px-1.5 py-0.5 rounded border border-border">
                cold_case.cases
              </code>{" "}
              reveals any cases missing an extraction (typically transient
              between ingestion and worker drain).
            </p>
          </div>
        </div>
      </section>

      {/* ─────────────── § 04 CORRELATION ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="04"
            id="correlation"
            eyebrow="Correlation engine"
            title={`How "cases with shared characteristics" get ranked.`}
            blurb={`On each cold-case detail page, a small panel surfaces other cases that share enough structural similarity to be worth an investigator's attention. Two hard filters (${weights.geo_miles} mi / ${weights.time_years} yr) precede a rarity-weighted score: matches on rare shared characteristics count for more than matches everyone shares. The ranking is intentionally conservative: high-signal candidates only, not every plausible match.`}
            rev={`rarity-weighted · top ${weights.top_n}`}
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-10">
            <Card>
              <CardContent className="p-5">
                <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                  Geographic filter
                </div>
                <div className="mb-2 text-3xl font-medium leading-none tracking-tight text-foreground">
                  ≤ {weights.geo_miles}
                  <span className="ml-1 text-sm font-normal text-muted-foreground">
                    miles
                  </span>
                </div>
                <p className="text-xs leading-normal text-muted-foreground">
                  Cross-metro pairs in serial-pattern data are usually
                  unrelated. Geography stays bounded.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                  Temporal filter
                </div>
                <div className="mb-2 text-3xl font-medium leading-none tracking-tight text-foreground">
                  ≤ {weights.time_years}
                  <span className="ml-1 text-sm font-normal text-muted-foreground">
                    years
                  </span>
                </div>
                <p className="text-xs leading-normal text-muted-foreground">
                  Time runs wide because cold-case patterns frequently span
                  dormant periods.
                </p>
              </CardContent>
            </Card>
          </div>

          <h3 className="text-lg font-medium tracking-snug text-foreground mb-4">
            Rarity-weighted scoring
          </h3>
          <div className="max-w-prose space-y-4 text-base leading-relaxed text-foreground mb-10">
            <p>
              A match is worth more when the shared characteristic is rare in
              the corpus. Two cases that both involve a firearm tell you little:
              firearms are everywhere in this data. Two cases that share an
              unusual weapon or an uncommon scene type are far more
              discriminating. Each matched dimension contributes a weight
              measured in bits of surprisal, computed from how often that exact
              value occurs across all cases. Rarer shared characteristics count
              for more; common ones count for almost nothing.
            </p>
            <p>
              Base rates are estimated with a small additive constant (a
              smoothing factor of{" "}
              <code className="font-mono text-sm bg-muted px-1.5 py-0.5 rounded">
                {weights.smoothing_alpha}
              </code>
              ), so a value that happens to be unique in the corpus today
              doesn&apos;t earn an unbounded weight tomorrow. The weights you see
              are derived live from the current corpus rather than hand-tuned
              constants. The engine reads its tunable parameters from a single
              module,{" "}
              <code className="font-mono text-sm bg-muted px-1.5 py-0.5 rounded">
                correlation/config.py
              </code>
              , so the scoring described here is the scoring the engine actually
              runs.
            </p>
          </div>

          <h3 className="text-lg font-medium tracking-snug text-foreground mb-4">
            Worked example
          </h3>
          <p className="max-w-prose text-base leading-relaxed text-muted-foreground mb-4">
            Bits earned by a match on each value, drawn live from the current
            corpus base rates. A common value and a rare value are shown per
            dimension so the spread is visible.
          </p>
          <Card className="overflow-hidden mb-4">
            <div className="grid grid-cols-[1.2fr_1.4fr_88px_70px] items-baseline gap-3 px-5 py-3 border-b border-border bg-muted/40 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
              <div>Dimension</div>
              <div>Value</div>
              <div>Rarity</div>
              <div className="text-right">Bits</div>
            </div>
            {weights.example_weights.map((ex) => (
              <ExampleRow
                key={`${ex.dimension}:${ex.value}`}
                dimension={ex.dimension}
                value={ex.value}
                bits={ex.bits}
                rarity={ex.rarity}
              />
            ))}
          </Card>
          <p className="max-w-prose text-sm leading-relaxed text-muted-foreground mb-10">
            Bits measure rarity: each extra bit means the shared value is about
            twice as rare in the data, so it counts for about twice as much in
            the score. A rarer value (more bits) is a stronger signal that two
            cases belong together; a value everyone shares barely moves the
            ranking.
          </p>

          <h3 className="text-lg font-medium tracking-snug text-foreground mb-4">
            Proximity discount
          </h3>
          <div className="max-w-prose space-y-4 text-base leading-relaxed text-foreground mb-10">
            <p>
              The rarity score is then discounted for how far apart the two
              cases are in space and time. The score is multiplied by a
              half-weight discount every{" "}
              <strong className="font-medium">
                {weights.distance_half_life_miles} miles
              </strong>{" "}
              of separation and again every{" "}
              <strong className="font-medium">
                {weights.time_half_life_years} years
              </strong>
              . A pair sharing strong characteristics across town keeps most of
              its score; the same pair fifty miles and two decades apart keeps
              little. The panel shows the surviving proximity factor next to
              each lead so the discount is visible, not hidden inside the
              number.
            </p>
          </div>

          <h3 className="text-lg font-medium tracking-snug text-foreground mb-4">
            When a case becomes a lead
          </h3>
          <div className="max-w-prose space-y-4 text-base leading-relaxed text-foreground mb-10">
            <p>
              A candidate is shown as a lead only when its discounted score
              clears a floor of{" "}
              <strong className="font-medium">{weights.score_floor}</strong> on a{" "}
              <strong className="font-medium">0 to {weights.score_scale}</strong>{" "}
              scale and it shares at least{" "}
              <strong className="font-medium">{weights.min_dimensions}</strong>{" "}
              characteristics with the focal case. Both conditions must hold: a
              single rare match isn&apos;t enough, and neither is a pile of
              common ones. Leads are ranked by score and the top{" "}
              <strong className="font-medium">{weights.top_n}</strong> are shown,
              with closer distance breaking ties.
            </p>
            <p>
              A classification of{" "}
              <code className="font-mono text-sm bg-muted px-1.5 py-0.5 rounded">
                unknown
              </code>{" "}
              on either case excludes that dimension from scoring. Two cases
              both classified{" "}
              <code className="font-mono text-sm bg-muted px-1.5 py-0.5 rounded">
                weapon = unknown
              </code>{" "}
              aren&apos;t matching on weapon; they&apos;re both cases where the
              narrative didn&apos;t specify a weapon. The same logic applies to
              missing demographics: if either case has no recorded victim
              gender, gender doesn&apos;t contribute.
            </p>
            <p>
              A low-confidence MO classification (paraphrased anchor) still
              counts as a match for scoring purposes. The panel displays the{" "}
              &ldquo;uncertain&rdquo; qualifier alongside the matched value so
              users see the weakened evidence without clicking through.
            </p>
          </div>

          <h3 className="text-lg font-medium tracking-snug text-foreground mb-4">
            Validation
          </h3>
          <div className="max-w-prose space-y-4 text-base leading-relaxed text-foreground mb-10">
            <p className="text-muted-foreground text-base">
              No public dataset records which cold cases are truly linked; if
              one existed, the linking would already be done. So the score is
              validated as a ranking aid, not against ground-truth links. Two
              checks bound its behavior: pairs known to belong to the same
              incident surface as each other&apos;s top matches at the highest
              proximity, while pairs connected only by an artifact of incomplete
              data (a placeholder date landing on a shared map centroid) stay
              below the lead threshold. The score orders candidates for human
              review; it does not assert that two cases are connected.
            </p>
          </div>

          <div className="max-w-prose space-y-4 text-base leading-relaxed text-foreground">
            <p className="text-muted-foreground text-base">
              <strong className="font-medium text-foreground">Scope.</strong>{" "}
              Correlation compares cold cases to other cold cases within the
              same dataset. Cross-corpus correlation against other record types
              is out of scope for this version: the data shapes differ, the join
              is more expensive, and the framing of &ldquo;potential leads&rdquo;
              needs separate methodological care before it&apos;s sound.
            </p>
          </div>
        </div>
      </section>

      {/* ─────────────── § 05 GEOCODING PRECISION ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="05"
            id="geocoding-precision"
            eyebrow="Geocoding precision"
            title="Four precision tiers, one map."
            blurb="Every case on the map carries one of four precision tiers, signaling how exactly the published source data lets us place the incident. Pins are styled differently per tier; click a county-precision pin to see the county boundary the case falls within."
            rev="tiers 1–4"
          />

          <div className="max-w-prose mb-10">
            <div className="rounded-md border border-border overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-muted/50 border-b border-border">
                    <th className="p-4 text-left font-medium text-foreground">Tier</th>
                    <th className="p-4 text-left font-medium text-foreground">Source</th>
                    <th className="p-4 text-left font-medium text-foreground">What it means</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-border">
                    <td className="p-4 font-mono font-medium text-foreground">street</td>
                    <td className="p-4 text-muted-foreground">Census or Google ROOFTOP</td>
                    <td className="p-4 text-muted-foreground">Exact address</td>
                  </tr>
                  <tr className="border-b border-border">
                    <td className="p-4 font-mono font-medium text-foreground">landmark</td>
                    <td className="p-4 text-muted-foreground">Google GEOMETRIC_CENTER / APPROXIMATE</td>
                    <td className="p-4 text-muted-foreground">Road, neighborhood, or city centroid</td>
                  </tr>
                  <tr className="border-b border-border">
                    <td className="p-4 font-mono font-medium text-foreground">zip</td>
                    <td className="p-4 text-muted-foreground">ZCTA centroid</td>
                    <td className="p-4 text-muted-foreground">Within this ZIP code area</td>
                  </tr>
                  <tr>
                    <td className="p-4 font-mono font-medium text-foreground">county</td>
                    <td className="p-4 text-muted-foreground">County centroid</td>
                    <td className="p-4 text-muted-foreground">Somewhere in this county (click pin to see boundary)</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="max-w-prose space-y-5 text-base leading-relaxed text-foreground">
            <p>
              The tier assigned to any case is determined by the best match
              returned from a three-step geocoding ladder. First, we try the
              Census Geocoding Service (free, maintained by EODC) against the
              published address; if that fails, we step down to Google&apos;s
              Geocoding API; if that also fails, we assign a ZIP centroid
              (ZCTA from the published postal code if available), then fall back
              to the county centroid where the case occurred.
            </p>
            <p>
              <strong className="font-medium text-foreground">County-precision pins</strong>
              are clickable on the map detail. Clicking zooms to show the
              full county boundary, a transparent wash that clarifies the
              uncertainty radius. Many cases from smaller counties or
              jurisdictions with incomplete narratives end up in tier 4;
              that&apos;s an honest representation of what the source told us,
              not a flaw in the geocoding.
            </p>
          </div>
        </div>
      </section>

      {/* ─────────────── § 06 BIAS & SELECTION EFFECTS ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="06"
            id="bias"
            eyebrow="Bias & selection effects"
            title="What the data is not."
            blurb="Every dataset assembled from public records carries selection effects. Latent Trace's are worth naming up front: an analyst who knows the shape of the bias can correct for it; one who doesn't will read artifacts as findings."
            rev="read before analyzing"
          />

          <div className="max-w-prose mb-8 text-base leading-relaxed text-foreground">
            <p>
              Latent Trace is a corpus of cold cases that an official publisher
              chose to make public and that Latent Trace has so far ingested. It
              is not a census of cold cases, and aggregate statistics drawn
              from it inherit every gap below. None of this makes the data
              unusable; it makes the data something you read with the
              following in hand.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[
              {
                label: "Publication bias",
                body: "Only cases an agency chose to post appear here. Agencies publish selectively: high-profile cases, cases where public tips help, cases that show the unit is active. A jurisdiction with no public roster contributes zero cases regardless of how many cold cases it carries.",
              },
              {
                label: "Geographic coverage follows publishers, not need",
                body: "Coverage tracks wherever an official source posts a usable roster, not population, not case density, not where help is most needed. Maryland appears county-by-county; most states aren't in yet. Cross-state comparison reflects ingestion order as much as anything real. See the §02 map for current shape.",
              },
              {
                label: "The corpus skews to still-unsolved",
                body: "Several sources are re-ingested live; cases solved between runs drop out. That keeps the data current but means Latent Trace trends toward cases that remain open; it is not a historical record of every case that was ever cold.",
              },
              {
                label: "Narrative framing carries through",
                body: "Extracted MO fields come from narratives written by law enforcement, in the language and emphasis the agency chose. 'Location type' reflects what a narrative foregrounded; a detail the writer omitted is a detail Latent Trace cannot recover.",
              },
              {
                label: "Demographic completeness varies by source",
                body: "Race is a structured first-party field in Colorado and Utah, absent from Maryland and DC narratives entirely. Any aggregate demographic figure is shaped by which states happen to be ingested, not a population-level measurement.",
              },
              {
                label: "Sources span different record-keeping eras",
                body: "Year ranges differ widely: Colorado reaches back to 1911, other sources are recent. Time-based analysis mixes decades of changing investigative practice, evidence standards, and what agencies recorded at all.",
              },
            ].map((item) => (
              <Card key={item.label}>
                <CardContent className="p-5">
                  <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                    Selection effect
                  </div>
                  <h3 className="text-base font-medium leading-snug tracking-snug text-foreground mb-2">
                    {item.label}
                  </h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {item.body}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* ─────────────── § 07 LIMITS ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="07"
            id="limits"
            eyebrow="Limits & open questions"
            title="What we know we don&apos;t know."
            blurb="Documented uncertainty is more useful than hidden uncertainty. The following are known v1 limitations, each with a route to resolution."
            rev="v1 known issues"
          />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[
              {
                label: "Paraphrased location extractions",
                body: "On the hand-labeled validation set, roughly one location classification in six resolves to a defensible paraphrase rather than a verbatim source span: the classification stands, the audit trail weakens. This is a validation-set rate, not a measured corpus-wide figure; it narrows with prompt iteration.",
              },
              {
                label: "Manual refresh cadence on most sources",
                body: "Most sources (Virginia VSPCCD among them) are re-ingested by hand when the publisher posts an update. There is no scheduled refresh today, so drift between a live site and our snapshot is bounded but real. The hero eyebrow shows the dataset's last ingestion date.",
              },
              {
                label: "Cross-source correlation is deferred",
                body: "Only cold-case ↔ cold-case in this version. Joining other record types needs methodological care before pairs are trustworthy.",
              },
              {
                label: "Multi-victim semantics use primary victim",
                body: "Demographic match against multi-victim cases pins to one victim per case. Rule is locked even at low incidence so behavior stays consistent as more multi-victim cases land.",
              },
              {
                label: "Race is never inferred from photographs",
                body: "An ethical guardrail, not a technical limitation. Cases without a source-stated race show as 'not provided' rather than imputing a value from imagery or names; the correlation engine treats race as unknown for those cases.",
              },
              {
                label: "Single primary photo per case",
                body: "Schema supports multiple photos per case but only the primary is rendered today. SHA256 captured for future dedup work.",
              },
            ].map((item) => (
              <Card key={item.label}>
                <CardContent className="p-5">
                  <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                    Known limitation
                  </div>
                  <h3 className="text-base font-medium leading-snug tracking-snug text-foreground mb-2">
                    {item.label}
                  </h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {item.body}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* ─────────────── § 08 CITATION ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="08"
            id="citation"
            eyebrow="Citation & reuse"
            title="Take what you need; cite the substrate."
            blurb="Underlying source data is published as public records by the originating agencies. Latent Trace aggregates, structures, and annotates. Researchers and journalists are welcome to use whatever they find; a citation back to this dataset is appreciated and lets readers trace provenance themselves."
          />

          <Card className="mb-6">
            <CardContent className="p-7">
              <div className="mb-3 font-mono text-2xs uppercase tracking-eyebrow text-accent">
                Suggested citation
              </div>
              <pre className="font-mono text-sm leading-relaxed text-foreground whitespace-pre-wrap break-words">
                {`Latent Trace Cold-Case Dataset. Dataset ${filterOptions.dataset.version}${
                  citationRevision ? `, revised ${citationRevision}` : ""
                }.\nRetrieved from ${siteUrl}/methodology.`}
              </pre>
            </CardContent>
          </Card>

          <p className="max-w-prose text-base leading-relaxed text-muted-foreground">
            If you&apos;re considering re-using extracted fields in a
            downstream system: please retain the source-span provenance so
            your readers can audit the inference chain back to the original
            narrative. The whole point of anchoring extractions to verbatim
            phrases is that the trust signal travels with the data. Tip-line
            and corrections:{" "}
            <a
              href="mailto:courtney@latenttrace.org"
              className="text-accent hover:underline"
            >
              courtney@latenttrace.org
            </a>
            .
          </p>
        </div>
      </section>

      {/* ─────────────── § 09 REVISION HISTORY ─────────────── */}
      <section className="px-8 sm:px-12 py-16 border-t border-border">
        <div className="mx-auto max-w-reading">
          <SectionHeader
            mark="09"
            id="revision-history"
            eyebrow="Revision history"
            title="What changed, and when."
            blurb="This page is versioned. Substantive changes to how the data is built or documented are logged here, so a claim you cite today can be checked against the methodology as it stood when you cited it."
            rev={`${METHODOLOGY_REVISIONS.length} entries`}
          />

          <ol className="max-w-prose border-l border-border">
            {METHODOLOGY_REVISIONS.map((entry) => (
              <li key={entry.date} className="relative pl-6 pb-6 last:pb-0">
                <span
                  aria-hidden
                  className="absolute left-[-4.5px] top-1.5 h-[8px] w-[8px] rounded-full bg-accent"
                />
                <time
                  dateTime={entry.date}
                  className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground"
                >
                  {entry.date}
                </time>
                <p className="mt-1 text-sm leading-relaxed text-foreground">
                  {entry.note}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </main>
  );
}
