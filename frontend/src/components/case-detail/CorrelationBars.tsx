"use client";

import Link from "next/link";
import { track } from "@/lib/analytics/client";

export interface MatchedDimension {
  name: string;
  value: string;
  low_confidence: boolean;
  weight: number;
}
export interface CorrelationItem {
  case_id: number;
  slug: string;
  victim_primary_name: string | null;
  city: string | null;
  state: string;
  year: number;
  score: number;
  score_max: number;
  proximity_factor: number;
  matched_dimensions: MatchedDimension[];
  distance_miles: number;
  years_apart: number;
}

/** Dimension -> display label + segment color (ember-family ramp by weight). */
const DIMENSIONS: ReadonlyArray<{ key: string; label: string; color: string }> = [
  { key: "weapon", label: "Weapon", color: "var(--accent-2)" },
  { key: "location_type", label: "Location", color: "var(--accent)" },
  { key: "victim_gender", label: "Gender", color: "#a85a44" },
  { key: "victim_race", label: "Race", color: "#8a5142" },
  { key: "victim_age", label: "Age", color: "#6e4839" },
];
const COLOR = new Map(DIMENSIONS.map((d) => [d.key, d.color]));
const MO_KEYS = new Set(["weapon", "location_type"]);

function Bar({ item, fromCaseId, rank }: { item: CorrelationItem; fromCaseId: number; rank: number }) {
  const name = item.victim_primary_name ?? "Unidentified";
  const max = item.score_max > 0 ? item.score_max : 10;
  const meta = `${item.city ?? "Unknown"}, ${item.state} · ${item.year} · ${Math.round(item.distance_miles)}mi · ${item.years_apart}yr`;
  const breakdown = item.matched_dimensions
    .map((d) => {
      const label = DIMENSIONS.find((x) => x.key === d.name)?.label ?? d.name;
      const uncertain = d.low_confidence && MO_KEYS.has(d.name) ? " (uncertain)" : "";
      return `${label}: ${d.value}${uncertain}`;
    })
    .join(", ");
  return (
    <Link
      href={`/cold-cases/${item.case_id}/${item.slug}`}
      onClick={() => track("related_case_clicked", { from_case_id: fromCaseId, to_case_id: item.case_id, rank })}
      className="group block border-b border-hair py-2.5 last:border-b-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className={"font-display text-sm font-semibold " + (item.victim_primary_name === null ? "italic text-muted-foreground" : "text-foreground group-hover:text-accent")}>
          {name}
        </span>
        <span className="shrink-0">
          <span className="font-mono text-2xs text-faint">{meta}</span>
          <span className="ml-2 font-mono text-xs tabular-nums text-accent">{item.score.toFixed(1)}</span>
        </span>
      </div>
      <div
        role="img"
        aria-label={`Match on ${breakdown}`}
        className="mt-2 flex h-3 w-full overflow-hidden rounded bg-white/[.04]"
      >
        {item.matched_dimensions.map((d) => (
          <span
            key={d.name}
            data-seg={d.name}
            title={`${d.value}${d.low_confidence && MO_KEYS.has(d.name) ? " (uncertain)" : ""}`}
            style={{ width: `${(d.weight / max) * 100}%`, background: COLOR.get(d.name) ?? "#6e4839" }}
            className={d.low_confidence && MO_KEYS.has(d.name) ? "h-full opacity-60" : "h-full"}
          />
        ))}
      </div>
      <div className="mt-1.5 font-mono text-2xs text-faint">
        proximity x{item.proximity_factor.toFixed(2)} at {item.distance_miles.toFixed(0)} mi / {item.years_apart} yr
      </div>
    </Link>
  );
}

export function CorrelationBars({ items, fromCaseId }: { items: CorrelationItem[]; fromCaseId: number }) {
  const present = new Set(items.flatMap((i) => i.matched_dimensions.map((d) => d.name)));
  return (
    <div>
      <div className="px-1">
        {items.map((it, i) => (
          <Bar key={it.case_id} item={it} fromCaseId={fromCaseId} rank={i + 1} />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5 border-t border-hair pt-3">
        {DIMENSIONS.filter((d) => present.has(d.key)).map((d) => (
          <span key={d.key} className="inline-flex items-center gap-1.5 font-mono text-2xs uppercase tracking-eyebrow text-faint">
            <span className="inline-block size-2 rounded-[2px]" style={{ background: d.color }} />
            {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}
