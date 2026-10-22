"use client";

import { useSourceReveal, type Span } from "./SourceRevealController";
import { useSourceRevealCtx } from "./SourceRevealContext";
import { MOSection, type MOSectionExtraction } from "./MOSection";
import { NarrativeWithHighlights } from "./NarrativeWithHighlights";
import { Block } from "./Block";

export interface CaseNarrativeWithMOProps {
  extraction: MOSectionExtraction | null;
  aboutText: string | null;
  /** Confident per-victim demographic spans (from VictimSection
   *  age_extraction/gender_extraction) -- shown as standing highlights
   *  alongside the case-level extraction spans. */
  victimSpans?: Span[];
}

/**
 * Anchored, confident extracted fields -> narrative spans shown as standing
 * highlights. Low-confidence / unanchored / "unknown" fields are excluded
 * (they have no verbatim span to mark). Clicking "Source >" still promotes one
 * to transient for scroll + ring emphasis.
 */
function extractionSpans(ext: MOSectionExtraction | null): Span[] {
  if (!ext) return [];
  const fields = [ext.weapon, ext.location_type, ext.incident_date, ext.address];
  const spans: Span[] = [];
  for (const f of fields) {
    if (
      f &&
      !f.low_confidence &&
      f.value !== null &&
      f.value !== "unknown" &&
      f.source_start !== null &&
      f.source_end !== null
    ) {
      spans.push({ start: f.source_start, end: f.source_end });
    }
  }
  return spans;
}

/**
 * Left-column wrapper rendering the narrative + extracted MO. Reveal state
 * comes from SourceRevealContext when a provider is present (the detail page
 * wraps the whole grid so victim cards share it); otherwise a local fallback
 * keeps the component self-contained for isolated rendering/tests.
 */
export function CaseNarrativeWithMO({ extraction, aboutText, victimSpans = [] }: CaseNarrativeWithMOProps) {
  const local = useSourceReveal();
  const ctx = useSourceRevealCtx();
  const reveal = ctx ?? local;
  const spans = [...extractionSpans(extraction), ...victimSpans];

  return (
    <>
      {aboutText && (
        <Block title="Case narrative" headingId="narrative-heading" tag="Source text · highlighted">
          <NarrativeWithHighlights
            text={aboutText}
            transient={reveal.transient}
            persistent={spans}
            onClearAll={reveal.clearAll}
          />
        </Block>
      )}
      {extraction !== null ? (
        <MOSection
          extraction={extraction}
          onRevealConfident={reveal.revealConfident}
          hasNarrative={!!aboutText}
        />
      ) : (
        <Block title="Modus operandi" headingId="mo-section-heading" tag="Tier-1">
          <p className="text-sm italic text-muted-foreground">
            Modus operandi extraction pending. No MO classification has been
            computed for this case yet.
          </p>
        </Block>
      )}
    </>
  );
}
