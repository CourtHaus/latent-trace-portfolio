import type React from "react";
import { humanizeCaseType } from "@/lib/humanizeCaseType";
import { formatCaseDate } from "@/lib/formatCaseDate";
import { cn } from "@/lib/utils";

type ProvenanceSource = "source" | "tier2" | null;

export interface CaseHeroProps {
  source_case_id: string;
  victim_primary_name: string | null;
  case_type: string;
  incident_date: string | null;
  incident_date_source?: ProvenanceSource;
  city: string | null;
  state: string;
  latitude: string | null;
  longitude: string | null;
  /** Days since the incident — computed by the caller; null when undated. */
  daysOpen: number | null;
  /** Tier label shown in the eyebrow; null when no extraction ran. */
  extractionTier?: 1 | 2 | null;
}

function Spec({
  label,
  children,
  mono,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="px-0 py-4 pr-5 [&:not(:first-child)]:border-l [&:not(:first-child)]:border-hair [&:not(:first-child)]:pl-5">
      <div className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-faint">{label}</div>
      <div className={cn("text-sm text-foreground", mono && "font-mono tabular-nums")}>{children}</div>
    </div>
  );
}

function formatCoord(value: string | null): string | null {
  if (value == null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(4) : null;
}

/**
 * Latent Trace case hero: an ember eyebrow (id · type · provenance), a Saira display
 * name headline, and a hairline 4-up specs strip.
 */
export function CaseHero({
  source_case_id,
  victim_primary_name,
  case_type,
  incident_date,
  incident_date_source,
  city,
  state,
  latitude,
  longitude,
  daysOpen,
  extractionTier,
}: CaseHeroProps) {
  const displayName = victim_primary_name ?? "Unidentified";
  const location = [city, state].filter(Boolean).join(", ") || "Unknown";
  const lat = formatCoord(latitude);
  const lng = formatCoord(longitude);
  const coords = lat && lng ? `${lat}, ${lng}` : "Unknown";

  return (
    <header className="rounded-2xl border border-border bg-gradient-to-b from-card to-inset px-6 py-6 shadow-[inset_0_1px_0_rgba(255,255,255,.04)] sm:px-8">
      <p className="flex flex-wrap items-center gap-2.5 font-mono text-2xs uppercase tracking-eyebrow">
        <span className="text-accent">#{source_case_id}</span>
        <span className="text-faint">·</span>
        <span className="text-muted-foreground">{humanizeCaseType(case_type)}</span>
        <span className="text-faint">·</span>
        <span className="text-faint">
          {extractionTier != null ? `Tier-${extractionTier} extracted` : "Source record"}
        </span>
      </p>
      <h1 className="mt-2.5 font-display text-4xl font-bold leading-none tracking-tight text-foreground sm:text-5xl">
        {displayName}
      </h1>
      <div className="mt-5 grid grid-cols-2 border-t border-hair sm:grid-cols-4">
        <Spec label="Incident date">
          {incident_date ? (
            <>
              <span className="tabular-nums">{formatCaseDate(incident_date)}</span>
              {incident_date_source === "tier2" && (
                <span className="ml-1.5 text-2xs italic text-faint">(extracted)</span>
              )}
            </>
          ) : "Unknown"}
        </Spec>
        <Spec label="Recovery location">{location}</Spec>
        <Spec label="Coordinates" mono>{coords}</Spec>
        <Spec label="Days open" mono>{daysOpen != null ? daysOpen.toLocaleString() : "Unknown"}</Spec>
      </div>
    </header>
  );
}
