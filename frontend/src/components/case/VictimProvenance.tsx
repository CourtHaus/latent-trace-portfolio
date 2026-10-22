"use client";

import type { components } from "@/lib/api-types";
import { useSourceRevealCtx } from "@/components/case-detail/SourceRevealContext";
import { track } from "@/lib/analytics/client";

type ExtractedField = components["schemas"]["ExtractedField"];

export interface VictimProvenanceProps {
  /** The victim row's *_source tag for this field. */
  source: "source" | "tier2" | null;
  /** Per-victim extraction provenance (null when value is source-provided). */
  field: ExtractedField | null | undefined;
  fieldName: "victim_age" | "victim_gender";
  /** Victim display name, used only to disambiguate the button's accessible
   *  name on multi-victim cases ("Source for age, Betty Selby"). */
  victimName?: string;
}

/**
 * Provenance affordance for one victim demographic value. Source-provided
 * values render nothing. Tier-2 values render a "Source" button that
 * highlights the verbatim narrative span (via SourceRevealContext), degrading
 * to a static "(extracted from narrative)" suffix when the span can't be
 * anchored or no provider is mounted.
 */
export function VictimProvenance({ source, field, fieldName, victimName }: VictimProvenanceProps) {
  const ctx = useSourceRevealCtx();
  if (source !== "tier2") return null;

  const anchored =
    field != null &&
    !field.low_confidence &&
    field.source_start !== null &&
    field.source_end !== null;

  if (!ctx || !anchored) {
    return (
      <span className="ml-1.5 text-2xs italic text-faint">
        (extracted from narrative)
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        track("source_revealed", { field: fieldName });
        ctx.revealConfident({ start: field.source_start!, end: field.source_end! });
      }}
      aria-controls={ctx.hasNarrative ? "case-narrative" : undefined}
      className="ml-1.5 font-mono text-2xs text-accent transition-colors hover:underline"
    >
      Source
      <span className="sr-only">
        {fieldName === "victim_age" ? " for age" : " for gender"}
        {victimName ? `, ${victimName}` : ""}
      </span>{" "}
      <span aria-hidden="true">▸</span>
    </button>
  );
}
