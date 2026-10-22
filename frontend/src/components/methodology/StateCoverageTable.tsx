import type { SourceSummaryItem } from "@/lib/getSourcesSummary";
import {
  SOURCE_METADATA,
  MD_COVERAGE,
  type SourceMetadata,
} from "@/lib/methodology/sourceMetadata";

interface Props {
  sources: ReadonlyArray<SourceSummaryItem>;
}

interface StateGroup {
  state: string;
  sources: ReadonlyArray<SourceSummaryItem>;
  totalCases: number;
  totalGeocoded: number;
  yearMin: number | null;
  yearMax: number | null;
}

const STATE_NAMES: Record<string, string> = {
  VA: "Virginia",
  MD: "Maryland",
  DC: "District of Columbia",
  CO: "Colorado",
  UT: "Utah",
  OH: "Ohio",
  WY: "Wyoming",
  NH: "New Hampshire",
};

function groupByState(sources: ReadonlyArray<SourceSummaryItem>): StateGroup[] {
  const byState = new Map<string, SourceSummaryItem[]>();
  for (const s of sources) {
    const key = s.state ?? "—";
    if (!byState.has(key)) byState.set(key, []);
    byState.get(key)!.push(s);
  }
  const groups: StateGroup[] = [];
  for (const [state, items] of byState) {
    const totalCases = items.reduce((sum, s) => sum + s.case_count, 0);
    const totalGeocoded = items.reduce((sum, s) => sum + s.geocoded_count, 0);
    const yearMins = items.map((s) => s.year_min).filter((y): y is number => y != null);
    const yearMaxs = items.map((s) => s.year_max).filter((y): y is number => y != null);
    groups.push({
      state,
      sources: items,
      totalCases,
      totalGeocoded,
      yearMin: yearMins.length ? Math.min(...yearMins) : null,
      yearMax: yearMaxs.length ? Math.max(...yearMaxs) : null,
    });
  }
  return groups.sort((a, b) => b.totalCases - a.totalCases);
}

function formatYearRange(min: number | null, max: number | null): string {
  if (min == null && max == null) return "—";
  if (min == null) return `…–${max}`;
  if (max == null) return `${min}–…`;
  if (min === max) return String(min);
  return `${min}–${max}`;
}

function formatGeocodedPct(geocoded: number, total: number): string {
  if (total === 0) return "—";
  return `${((geocoded / total) * 100).toFixed(0)}%`;
}

export function StateCoverageTable({ sources }: Props) {
  const groups = groupByState(sources);

  return (
    <div className="rounded-md border border-border bg-card overflow-hidden">
      {/* Header */}
      <div
        className="
          hidden sm:grid
          grid-cols-[1.4fr_140px_90px_120px_90px]
          gap-4 px-5 py-3
          bg-muted/40 border-b border-border
          font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground
        "
      >
        <div>State</div>
        <div>Method</div>
        <div className="text-right tabular-nums">Cases</div>
        <div className="tabular-nums">Years</div>
        <div className="text-right tabular-nums">Geocoded</div>
      </div>

      {groups.map((group, idx) => (
        <StateRow
          key={group.state}
          group={group}
          isLast={idx === groups.length - 1}
        />
      ))}
    </div>
  );
}

interface StateRowProps {
  group: StateGroup;
  isLast: boolean;
}

function StateRow({ group, isLast }: StateRowProps) {
  const stateName = STATE_NAMES[group.state] ?? group.state;
  // For a multi-source state, surface a method summary like "6 sources · web scrape";
  // for a single-source state, surface the source's method directly.
  const firstSource = group.sources[0];
  const methodLabel =
    group.sources.length === 1 && firstSource
      ? (SOURCE_METADATA[firstSource.code]?.method ?? "—")
      : `${group.sources.length} sources`;

  const jurisdictionNote =
    group.state === "MD"
      ? ` (${MD_COVERAGE.covered.length} of ${
          MD_COVERAGE.covered.length +
          MD_COVERAGE.noRoster.length +
          MD_COVERAGE.stateHandled.length
        } jurisdictions)`
      : "";

  return (
    <details
      className={`group ${isLast ? "" : "border-b border-border"}`}
    >
      <summary
        className="
          grid grid-cols-[1.4fr_140px_90px_120px_90px]
          gap-4 px-5 py-4
          cursor-pointer list-none
          hover:bg-muted/30 transition-colors
          marker:hidden
        "
      >
        <div className="flex items-baseline gap-2.5">
          <span
            aria-hidden
            className="
              font-mono text-2xs text-muted-foreground/70
              group-open:rotate-90 transition-transform
              inline-block w-3
            "
          >
            ▸
          </span>
          <div>
            <div className="text-base font-medium text-foreground leading-tight">
              {stateName}
              <span className="ml-2 font-mono text-2xs text-muted-foreground">
                {group.state}
              </span>
            </div>
            {jurisdictionNote && (
              <div className="mt-0.5 text-xs text-muted-foreground">
                {jurisdictionNote.trim()}
              </div>
            )}
          </div>
        </div>
        <div className="text-sm text-muted-foreground self-center">
          {methodLabel}
        </div>
        <div className="text-right tabular-nums text-sm font-medium text-foreground self-center">
          {group.totalCases.toLocaleString()}
        </div>
        <div className="tabular-nums text-sm text-muted-foreground self-center">
          {formatYearRange(group.yearMin, group.yearMax)}
        </div>
        <div className="text-right tabular-nums text-sm text-muted-foreground self-center">
          {formatGeocodedPct(group.totalGeocoded, group.totalCases)}
        </div>
      </summary>

      <div className="px-5 pb-6 pt-2 bg-muted/20 border-t border-border/60">
        {group.sources.map((s) => (
          <SourceDetail key={s.code} source={s} />
        ))}
        {group.state === "MD" && <MarylandCoveragePanel />}
      </div>
    </details>
  );
}

function SourceDetail({ source }: { source: SourceSummaryItem }) {
  const meta: SourceMetadata | undefined = SOURCE_METADATA[source.code];
  const displayName = meta?.displayName ?? source.name;

  return (
    <div className="mt-5 first:mt-3 rounded-md border border-border bg-card p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-2xs uppercase tracking-eyebrow text-accent">
            {meta?.shortLabel ?? source.code}
          </span>
          <span className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
            {meta?.agencyType ?? "—"} · {meta?.jurisdiction ?? "—"}
          </span>
        </div>
        <span className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
          {meta?.method ?? "—"}
        </span>
      </div>

      <h4 className="text-base font-medium tracking-snug text-foreground mb-2">
        {displayName}
      </h4>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3 text-xs">
        <div>
          <div className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
            Cases
          </div>
          <div className="mt-0.5 tabular-nums font-medium text-foreground">
            {source.case_count.toLocaleString()}{" "}
            <span className="text-muted-foreground">
              · {formatGeocodedPct(source.geocoded_count, source.case_count)} geocoded
            </span>
          </div>
        </div>
        <div>
          <div className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
            Year range
          </div>
          <div className="mt-0.5 tabular-nums text-foreground">
            {formatYearRange(source.year_min, source.year_max)}
          </div>
        </div>
        <div>
          <div className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
            Geocoding
          </div>
          <div className="mt-0.5 text-foreground text-xs leading-snug">
            {meta?.geocodingStrategy ?? "—"}
          </div>
        </div>
      </div>

      {meta?.notes && (
        <p className="text-sm leading-relaxed text-muted-foreground mb-3">
          {meta.notes}
        </p>
      )}

      {meta?.caveats && meta.caveats.length > 0 && (
        <div className="space-y-2 mb-3">
          {meta.caveats.map((c) => (
            <div
              key={c.title}
              className="rounded-md border border-border bg-muted/40 p-3"
            >
              <div className="mb-1 font-mono text-2xs uppercase tracking-eyebrow text-accent">
                {c.title}
              </div>
              <p className="text-xs leading-normal text-muted-foreground">
                {c.body}
              </p>
            </div>
          ))}
        </div>
      )}

      {meta?.url && (
        <a
          href={meta.url}
          target="_blank"
          rel="noopener"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
        >
          {meta.url.replace(/^https?:\/\//, "").replace(/\/$/, "")} →
        </a>
      )}
    </div>
  );
}

function MarylandCoveragePanel() {
  const total =
    MD_COVERAGE.covered.length +
    MD_COVERAGE.noRoster.length +
    MD_COVERAGE.stateHandled.length;
  return (
    <div className="mt-5 rounded-md border border-border bg-card p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h4 className="font-mono text-2xs uppercase tracking-eyebrow text-accent">
          Maryland sub-state coverage
        </h4>
        <span className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
          {MD_COVERAGE.covered.length} of {total} jurisdictions
        </span>
      </div>
      <p className="mb-4 text-sm leading-relaxed text-muted-foreground">
        Latent Trace ingests only first-party county or municipal sources. Where a
        Maryland jurisdiction has no public cold-case roster, the cases
        aren&apos;t here. That is a source-integrity choice, not an omission.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-[140px_1fr] gap-x-5 gap-y-3 text-xs">
        <div className="text-foreground font-medium">
          Covered{" "}
          <span className="text-muted-foreground">({MD_COVERAGE.covered.length})</span>
        </div>
        <div className="text-muted-foreground">{MD_COVERAGE.covered.join(" · ")}</div>

        <div className="text-foreground font-medium">
          No public roster{" "}
          <span className="text-muted-foreground">({MD_COVERAGE.noRoster.length})</span>
        </div>
        <div className="text-muted-foreground">{MD_COVERAGE.noRoster.join(" · ")}</div>

        <div className="text-foreground font-medium">
          State-handled{" "}
          <span className="text-muted-foreground">
            ({MD_COVERAGE.stateHandled.length})
          </span>
        </div>
        <div className="text-muted-foreground">
          {MD_COVERAGE.stateHandled.join(" · ")} (Maryland State Police)
        </div>
      </div>
      <p className="mt-3 text-2xs leading-normal text-muted-foreground/80">
        Queen Anne&apos;s County hosts a 2-case page (1 homicide, 1 missing
        person); below the threshold for a dedicated adapter. Revisit when the
        page grows.
      </p>
    </div>
  );
}
