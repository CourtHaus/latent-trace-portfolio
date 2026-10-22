import { getFilterOptionsOrNull } from "@/lib/getFilterOptions";

/**
 * Passive metadata strip above the nav.
 * Reads filter-options (cached 1hr browser + 24hr SWR per A4).
 * Signals "live data" without adding interactivity.
 */
export async function StatusStrip() {
  const options = await getFilterOptionsOrNull();

  const datasetVersion = options?.dataset.version ?? "n/a";
  const states = options?.states ?? [];
  const systemCount = options?.source_systems.length ?? 0;
  const lastIngestedLabel = options?.dataset.last_ingested
    ? formatRelativeDays(new Date(options.dataset.last_ingested))
    : "n/a";

  return (
    <div className="border-b border-hair bg-card text-faint">
      <div className="bleed flex h-[30px] items-center justify-between gap-4 font-mono text-2xs uppercase tracking-eyebrow">
        <div className="flex items-center gap-2">
          <span
            className="pulse-live inline-block h-1.5 w-1.5 rounded-full bg-primary"
            aria-hidden="true"
          />
          <span>LIVE · DATASET {datasetVersion}</span>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <span>Monitoring {systemCount} systems</span>
        </div>
        <div className="flex items-center gap-5">
          <span className="hidden lg:inline">
            States{" "}
            <span className="normal-case tracking-normal text-foreground/80">
              {states.join(", ")}
            </span>
          </span>
          <span className="lg:hidden">{states.length} states</span>
          <span>
            <span className="hidden lg:inline">Last ingested </span>
            <span className="normal-case tracking-normal text-foreground/80">
              {lastIngestedLabel}
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}

function formatRelativeDays(date: Date): string {
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "1d ago";
  if (diffDays < 30) return `${diffDays}d ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}
