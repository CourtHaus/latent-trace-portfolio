"use client";

import { useState, useRef, useEffect, useId } from "react";
import { MethodologyLink } from "@/components/MethodologyLink";
import { track } from "@/lib/analytics/client";
import { Block } from "./Block";

interface ExtractedField {
  value: string | null;
  raw_phrase: string | null;
  source_start: number | null;
  source_end: number | null;
  low_confidence: boolean;
}

export interface MOSectionExtraction {
  weapon: ExtractedField;
  location_type: ExtractedField;
  // Tier-2 (optional, present when the source needed narrative extraction
  // for these fields — BCounty does, VA doesn't).
  incident_date?: ExtractedField | null;
  address?: ExtractedField | null;
  // victim_age and victim_gender have moved to per-victim cards
  // (VictimSection.age_extraction / gender_extraction).
  model_id: string;
  extracted_at: string;
}

export interface MOSectionProps {
  extraction: MOSectionExtraction;
  onRevealConfident: (span: { start: number; end: number }) => void;
  /**
   * Whether the case narrative (`#case-narrative`) is rendered. The confident
   * "Source" button references it via aria-controls; only emit that reference
   * when the target actually exists, else it dangles. Defaults to false so a
   * direct render without a narrative never points at a missing element.
   */
  hasNarrative?: boolean;
}

type TrackedFieldName = "weapon" | "location_type" | "incident_date" | "address";

type FieldState =
  | { kind: "confident"; value: string; span: { start: number; end: number } }
  | { kind: "low_conf"; value: string; rawPhrase: string | null }
  | { kind: "unknown" }
  | { kind: "unavailable" };

function classify(field: ExtractedField): FieldState {
  if (field.value === null && field.low_confidence) return { kind: "unavailable" };
  if (field.value === "unknown") return { kind: "unknown" };
  if (field.low_confidence) {
    return {
      kind: "low_conf",
      value: field.value as string,
      rawPhrase: field.raw_phrase,
    };
  }
  if (field.source_start !== null && field.source_end !== null) {
    return {
      kind: "confident",
      value: field.value as string,
      span: { start: field.source_start, end: field.source_end },
    };
  }
  // Defensive: confident value but missing offsets — degrade to low_conf
  return {
    kind: "low_conf",
    value: field.value as string,
    rawPhrase: field.raw_phrase,
  };
}

interface PopoverProps {
  rawPhrase: string | null;
  fieldName: TrackedFieldName;
}

function LowConfPopover({ rawPhrase, fieldName }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      if (e instanceof MouseEvent && ref.current?.contains(e.target as Node)) return;
      setOpen(false);
      if (e instanceof KeyboardEvent) e.stopPropagation();
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", handler);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => {
          track("source_revealed", { field: fieldName });
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="font-mono text-2xs text-accent transition-colors hover:underline"
      >
        Source <span aria-hidden="true">▸</span>
      </button>
      {open && (
        <div
          id={panelId}
          className="absolute left-0 z-20 mt-1 w-72 rounded-md border border-border bg-elev p-3 text-sm text-muted-foreground shadow-md"
        >
          {rawPhrase ? (
            <>
              Model returned phrase: <em>&ldquo;{rawPhrase}&rdquo;</em>. Couldn&apos;t
              anchor verbatim. Scan the narrative for similar wording.
            </>
          ) : (
            <>Classified based on narrative context. No specific phrase identified.</>
          )}
        </div>
      )}
    </div>
  );
}

interface FieldRowProps {
  label: string;
  fieldName: TrackedFieldName;
  state: FieldState;
  onRevealConfident: (span: { start: number; end: number }) => void;
  hasNarrative: boolean;
}

function FieldLabel({ children }: { children: string }) {
  return (
    <span className="font-mono text-2xs uppercase tracking-snug text-faint">{children}</span>
  );
}

function FieldRow({ label, fieldName, state, onRevealConfident, hasNarrative }: FieldRowProps) {
  if (state.kind === "unknown") {
    return (
      <div className="flex flex-wrap items-baseline gap-x-2 text-sm text-muted-foreground">
        <FieldLabel>{label}</FieldLabel> not mentioned in case file
      </div>
    );
  }
  if (state.kind === "unavailable") {
    return (
      <div className="flex flex-wrap items-baseline gap-x-2 text-sm italic text-muted-foreground">
        <FieldLabel>{label}</FieldLabel> extraction unavailable
      </div>
    );
  }
  if (state.kind === "confident") {
    return (
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
        <FieldLabel>{label}</FieldLabel>
        <span className="text-foreground">{state.value}</span>
        <button
          type="button"
          onClick={() => {
            track("source_revealed", { field: fieldName });
            onRevealConfident(state.span);
          }}
          aria-controls={hasNarrative ? "case-narrative" : undefined}
          className="font-mono text-2xs text-accent transition-colors hover:underline"
        >
          Source <span aria-hidden="true">▸</span>
        </button>
      </div>
    );
  }
  // low_conf
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
      <FieldLabel>{label}</FieldLabel>
      <span className="italic text-foreground">{state.value}</span>
      <span className="text-2xs text-faint">uncertain</span>
      <LowConfPopover rawPhrase={state.rawPhrase} fieldName={fieldName} />
    </div>
  );
}

export function MOSection({ extraction, onRevealConfident, hasNarrative = false }: MOSectionProps) {
  const weaponState = classify(extraction.weapon);
  const locationState = classify(extraction.location_type);
  const bothUnknownOrAbsent =
    (weaponState.kind === "unknown" || weaponState.kind === "unavailable") &&
    (locationState.kind === "unknown" || locationState.kind === "unavailable");
  const showCollapsedSummary =
    weaponState.kind === "unknown" && locationState.kind === "unknown";

  const hasTier2 = !!(extraction.incident_date || extraction.address);

  return (
    <Block
      title="Modus operandi"
      headingId="mo-section-heading"
      tag={hasTier2 ? "Tier-1 + Tier-2" : "Tier-1"}
      bodyClassName="space-y-3"
    >
      {showCollapsedSummary ? (
        <p className="text-sm text-muted-foreground">
          No modus operandi could be extracted from the narrative.
        </p>
      ) : (
        <>
          <FieldRow
            label="Weapon"
            fieldName="weapon"
            state={weaponState}
            onRevealConfident={onRevealConfident}
            hasNarrative={hasNarrative}
          />
          <FieldRow
            label="Location"
            fieldName="location_type"
            state={locationState}
            onRevealConfident={onRevealConfident}
            hasNarrative={hasNarrative}
          />
        </>
      )}
      {hasTier2 && (
        <div className="space-y-2 border-t border-hair pt-3">
          {extraction.incident_date && (
            <FieldRow
              label="Date"
              fieldName="incident_date"
              state={classify(extraction.incident_date)}
              onRevealConfident={onRevealConfident}
              hasNarrative={hasNarrative}
            />
          )}
          {extraction.address && (
            <FieldRow
              label="Address"
              fieldName="address"
              state={classify(extraction.address)}
              onRevealConfident={onRevealConfident}
              hasNarrative={hasNarrative}
            />
          )}
        </div>
      )}
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-t border-hair pt-3">
        <MethodologyLink section="modus-operandi">About these fields →</MethodologyLink>
        {!bothUnknownOrAbsent && (
          <span className="font-mono text-2xs text-faint">
            {extraction.model_id} · {new Date(extraction.extracted_at).toLocaleDateString()}
          </span>
        )}
      </div>
    </Block>
  );
}
