import Link from "next/link";
import type { LandingCase } from "@/lib/getLandingCases";
import { MiniMap } from "@/components/landing/viz/MiniMap";
import { ZigZagSection } from "@/components/landing/ZigZagSection";

export interface TwoWaysInProps {
  recentCases: LandingCase[];
}

function MiniIndex({ cases }: { cases: LandingCase[] }) {
  return (
    <div>
      {cases.slice(0, 4).map((c) => (
        <div
          key={c.case_id}
          className="grid grid-cols-[62px_1fr_40px] items-center gap-2.5 border-b border-hair py-2 text-xs last:border-none"
        >
          <span className="font-mono text-2xs text-faint">
            {c.source_case_id}
          </span>
          <span className="truncate">
            {c.victim_primary_name ?? "Unidentified"}
          </span>
          <span className="text-right font-mono text-2xs text-muted-foreground">
            {c.incident_date?.slice(0, 4) ?? "n/a"}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Section 03: Two ways in. Server component. */
export function TwoWaysIn({ recentCases }: TwoWaysInProps) {
  return (
    <ZigZagSection
      index="02"
      id="d2"
      title="Two ways in"
      desc="The same corpus, queried two ways: a searchable register and a geospatial view."
      align="left"
      banded={true}
    >
      <div className="grid gap-4.5 sm:grid-cols-2">
        {/* Card 1: Case register */}
        <Link
          href="/cold-cases"
          className="group block overflow-hidden rounded-2xl border border-border bg-gradient-to-b from-card to-inset transition-[transform,border-color,box-shadow] hover:-translate-y-1 hover:border-accent/50 hover:shadow-[0_30px_70px_rgba(0,0,0,.5)]"
        >
          <div className="flex justify-between border-b border-hair px-4.5 py-3.5 font-mono text-2xs uppercase tracking-eyebrow text-faint">
            <span>MOD-01 · Ledger</span>
            <span>Searchable</span>
          </div>
          <div className="min-h-[148px] px-4.5 py-4">
            <MiniIndex cases={recentCases} />
          </div>
          <div className="px-5.5 pb-5.5 pt-1">
            <h3 className="font-display text-2xl font-bold tracking-snug">
              The case register
            </h3>
            <p className="mt-2 text-sm leading-normal text-muted-foreground">
              Every record, filterable across jurisdiction, type, demographics,
              and modus operandi. Sortable, paginated, traceable to its source
              entry.
            </p>
            <span className="mt-4 inline-flex font-mono text-2xs uppercase tracking-widest text-muted-foreground transition-colors group-hover:text-accent">
              Open the ledger
            </span>
          </div>
        </Link>

        {/* Card 2: Map */}
        <Link
          href="/cold-cases/map"
          className="group block overflow-hidden rounded-2xl border border-border bg-gradient-to-b from-card to-inset transition-[transform,border-color,box-shadow] hover:-translate-y-1 hover:border-accent/50 hover:shadow-[0_30px_70px_rgba(0,0,0,.5)]"
        >
          <div className="flex justify-between border-b border-hair px-4.5 py-3.5 font-mono text-2xs uppercase tracking-eyebrow text-faint">
            <span>MOD-02 · Geospatial</span>
            <span>Interactive</span>
          </div>
          <div className="min-h-[148px] px-4.5 py-4">
            <MiniMap />
          </div>
          <div className="px-5.5 pb-5.5 pt-1">
            <h3 className="font-display text-2xl font-bold tracking-snug">
              Where the cases are
            </h3>
            <p className="mt-2 text-sm leading-normal text-muted-foreground">
              Cases plotted to incident location, clustered by region,
              cross-filtered against the same ledger query.
            </p>
            <span className="mt-4 inline-flex font-mono text-2xs uppercase tracking-widest text-muted-foreground transition-colors group-hover:text-accent">
              Open the map
            </span>
          </div>
        </Link>
      </div>
    </ZigZagSection>
  );
}
