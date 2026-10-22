"use client";

import { MethodologyLink } from "@/components/MethodologyLink";
import { Block } from "./Block";
import { CorrelationBars } from "./CorrelationBars";

interface MatchedDimensionPayload {
  name: string;
  value: string;
  low_confidence: boolean;
  weight: number;
}

export interface Correlation {
  case_id: number;
  slug: string;
  victim_primary_name: string | null;
  city: string | null;
  state: string;
  year: number;
  score: number;
  score_max: number;
  proximity_factor: number;
  matched_dimensions: MatchedDimensionPayload[];
  distance_miles: number;
  years_apart: number;
}

interface ExtractedField {
  value: string | null;
  raw_phrase: string | null;
  source_start: number | null;
  source_end: number | null;
  low_confidence: boolean;
}

interface ParentExtraction {
  weapon: ExtractedField;
  location_type: ExtractedField;
  model_id: string;
  extracted_at: string;
}

export interface RelatedCasesPanelProps {
  parentExtraction: ParentExtraction | null;
  correlations: Correlation[];
  fromCaseId: number;
}

function isContributingMODim(field: ExtractedField | undefined | null): boolean {
  if (!field) return false;
  return field.value !== null && field.value !== "unknown";
}


function bannerFor(extraction: ParentExtraction | null): string | null {
  if (extraction === null) {
    return "MO classification not available for this case. Correlations limited to demographic matches in geographic and temporal proximity.";
  }
  const weaponContributes = isContributingMODim(extraction.weapon);
  const locationContributes = isContributingMODim(extraction.location_type);
  if (weaponContributes && locationContributes) return null;
  if (!weaponContributes && !locationContributes) {
    return "MO classification not available for this case. Correlations limited to demographic matches in geographic and temporal proximity.";
  }
  // Exactly one contributes — name the AVAILABLE dim
  const availableDim = weaponContributes ? "weapon" : "location type";
  return `Only the ${availableDim} dimension is available for this case. Correlations score on one MO dimension plus demographics.`;
}


function EmptyState() {
  return (
    <p className="text-sm text-muted-foreground">
      No plausible matches in geographic + temporal proximity.{" "}
      <MethodologyLink section="correlation">Methodology →</MethodologyLink>
    </p>
  );
}


export function RelatedCasesPanel({
  parentExtraction,
  correlations,
  fromCaseId,
}: RelatedCasesPanelProps) {
  const banner = bannerFor(parentExtraction);

  return (
    <Block
      title={`Cases with shared characteristics (${correlations.length})`}
      headingId="related-cases-heading"
      tag={correlations.length > 0 ? `Top ${correlations.length}` : undefined}
      bodyClassName="space-y-3"
    >
      {banner && <p className="text-2xs italic leading-relaxed text-faint">{banner}</p>}
      {correlations.length === 0 ? (
        <EmptyState />
      ) : (
        <CorrelationBars items={correlations} fromCaseId={fromCaseId} />
      )}
      <div className="border-t border-hair pt-3">
        <MethodologyLink section="correlation">About this →</MethodologyLink>
      </div>
    </Block>
  );
}
