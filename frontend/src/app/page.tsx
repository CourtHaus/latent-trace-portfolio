import { Hero } from "@/components/landing/Hero";
import { Reveal } from "@/components/landing/Reveal";
import { MethodologyBand } from "@/components/landing/sections/MethodologyBand";
import { TwoWaysIn } from "@/components/landing/sections/TwoWaysIn";
import { Correlation } from "@/components/landing/sections/Correlation";
import { Distribution } from "@/components/landing/sections/Distribution";
import { Provenance } from "@/components/landing/sections/Provenance";
import { getFilterOptions } from "@/lib/getFilterOptions";
import { getDatasetCounts } from "@/lib/getDatasetCounts";
import { getYearHistogramOrNull, bucketByDecade } from "@/lib/getYearHistogram";
import { getSourcesSummaryOrNull } from "@/lib/getSourcesSummary";
import { getLandingCasesOrEmpty } from "@/lib/getLandingCases";
import { getCoverageHistogram } from "@/lib/getCoverageHistogram";
import { buildCoverageMatrix } from "@/lib/coverageMatrix";
import { getFeaturedCorrelation } from "@/lib/getFeaturedCorrelation";
import { toRidgeRows } from "@/lib/decadeHistogram";
import type { Metadata } from "next";

export const metadata: Metadata = {
  description:
    "A unified, source-attributed corpus of unsolved cold homicide cases from official law-enforcement records: searchable, mapped, and correlated.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Latent Trace",
    description:
      "Unsolved cold homicide cases from official sources, unified and searchable.",
    url: "/",
  },
};

export default async function HomePage() {
  // filterOptions + counts drive the Hero's headline figures and intentionally
  // throw on failure: a transient blip should retry, not cache a misleading
  // zero-state into ISR. The remaining fetches back decorative sections, so
  // they use resilient variants — a single cold-start 500 degrades that section
  // (renders empty / omitted) instead of failing the whole landing page.
  const [filterOptions, counts, histogram, sources, recentCases, coverage, correlation] = await Promise.all([
    getFilterOptions(),
    getDatasetCounts(),
    getYearHistogramOrNull(),
    getSourcesSummaryOrNull(),
    getLandingCasesOrEmpty(),
    getCoverageHistogram(),
    getFeaturedCorrelation(),
  ]);

  const { rows: coverageRows, values: coverageValues } = buildCoverageMatrix(coverage.buckets);

  const total = counts.totalUnfiltered;
  const geocodedPct = total > 0 ? Math.round((counts.geocodedUnfiltered / total) * 100) : 0;
  const spanYears =
    filterOptions.year_range.max != null && filterOptions.year_range.min != null
      ? filterOptions.year_range.max - filterOptions.year_range.min
      : 0;
  const jurisdictions = filterOptions.source_systems.length;

  const ridgeRows = toRidgeRows(
    bucketByDecade(histogram?.buckets ?? [], 1960).map((b) => ({
      decade: b.decade,
      count: b.count,
    })),
  );

  return (
    <main id="main">
      <Hero
        total={total}
        geocodedPct={geocodedPct}
        spanYears={spanYears}
        jurisdictions={jurisdictions}
        ridgeRows={ridgeRows}
      />

      {/* Each section component self-renders its own <section> with border/padding/bg.
          Reveal wraps only need a neutral div pass-through. */}
      <Reveal><MethodologyBand /></Reveal>
      <Reveal><TwoWaysIn recentCases={recentCases} /></Reveal>
      <Reveal><Correlation points={correlation.points} leads={correlation.leads} /></Reveal>
      <Reveal>
        <Distribution
          ridgeRows={ridgeRows}
          coverageRows={coverageRows}
          coverageValues={coverageValues}
        />
      </Reveal>
      <Reveal><Provenance sources={sources?.data ?? []} /></Reveal>
    </main>
  );
}
