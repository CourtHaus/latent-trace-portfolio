import type { SourceSummaryItem } from "@/lib/getSourcesSummary";
import { ZigZagSection } from "@/components/landing/ZigZagSection";

export interface ProvenanceProps {
  sources: SourceSummaryItem[];
}

/** Coverage bar derived from geocoded_count / case_count (SourceSummaryItem has no explicit pct field). */
function CoverageBar({ geocodedCount, caseCount }: { geocodedCount: number; caseCount: number }) {
  const pct = caseCount > 0 ? Math.round((geocodedCount / caseCount) * 100) : 0;
  return (
    <span
      role="img"
      className="block h-[6px] overflow-hidden rounded-[3px] bg-white/[.06]"
      aria-label={`${pct}% geocoded`}
    >
      <i
        className="block h-full rounded-[3px] bg-gradient-to-r from-accent to-accent-2 not-italic"
        style={{ width: `${pct}%` }}
      />
    </span>
  );
}

/** Year range label for the sync column. Falls back to "recent" when unknown. */
function syncLabel(item: SourceSummaryItem): string {
  if (item.year_max != null) return String(item.year_max);
  return "recent";
}

/** Section 06: Provenance ledger. Server component. */
export function Provenance({ sources }: ProvenanceProps) {
  const ranked = [...sources].sort((a, b) => b.case_count - a.case_count);

  return (
    <ZigZagSection
      index="05"
      id="d5"
      title="Provenance"
      desc="Every record ingested from a first-party public source and kept attributable."
      link={{ href: "/methodology", label: "Read methodology" }}
      align="right"
      banded={false}
    >
      <div className="overflow-hidden rounded-2xl border border-border bg-gradient-to-b from-card to-inset">
          {/* Header row — desktop grid only; on mobile each row is a stacked card. */}
          <div className="hidden sm:grid grid-cols-[140px_1fr_1.3fr_90px_70px] items-center gap-4.5 border-b border-hair px-6 py-3.5 font-mono text-2xs uppercase tracking-eyebrow text-faint">
            <span>Source</span>
            <span>Jurisdiction</span>
            <span>Coverage</span>
            <span className="text-right">Records</span>
            <span className="text-right">Latest</span>
          </div>

          {/* Data rows — stacked on mobile, 5-col grid at sm+ */}
          {ranked.map((s) => (
            <div
              key={s.code}
              className="flex flex-col gap-1.5 border-b border-hair px-5 py-3.5 transition-colors last:border-none hover:bg-white/[.025] sm:grid sm:grid-cols-[140px_1fr_1.3fr_90px_70px] sm:items-center sm:gap-4.5 sm:px-6 sm:py-3.5"
            >
              <span className="font-mono text-xs text-foreground">
                {s.code}
              </span>
              <span className="text-sm text-muted-foreground">
                {s.state ?? s.name}
              </span>
              <CoverageBar geocodedCount={s.geocoded_count} caseCount={s.case_count} />
              <span className="font-mono text-xs tabular-nums text-foreground sm:text-right">
                {s.case_count.toLocaleString()}
              </span>
              <span className="font-mono text-2xs text-faint sm:text-right">
                {syncLabel(s)}
              </span>
            </div>
          ))}
        </div>
    </ZigZagSection>
  );
}
