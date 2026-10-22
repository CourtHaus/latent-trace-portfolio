"use client";

import { XIcon } from "lucide-react";

import { humanizeCaseType } from "@/lib/humanizeCaseType";
import { track } from "@/lib/analytics/client";

export type AppliedFilterDimension =
  | "year"
  | "caseType"
  | "city"
  | "victimGender"
  | "victimRace"
  | "weapon"
  | "locationType"
  | "sourceSystem"
  | "precision";

export interface AppliedFilters {
  yearMin: number | null;
  yearMax: number | null;
  caseType: string[];
  city: string | null;
  victimGender: string[];
  victimRace: string[];
  weapon: string[];
  locationType: string[];
  /** Resolved {code, name} pairs so the chip body shows the user-visible name. */
  sourceSystem: { code: string; name: string }[];
  precision: string[];
}

export interface AppliedFilterChipsProps {
  filters: AppliedFilters;
  onClearDimension: (dim: AppliedFilterDimension) => void;
  onClearAll: () => void;
}

const MAX_VALUES_BEFORE_OVERFLOW = 3;

interface ChipDescriptor {
  dim: AppliedFilterDimension;
  label: string;
  body: string;
}

function multiValueBody(values: string[]): string {
  if (values.length <= MAX_VALUES_BEFORE_OVERFLOW) {
    return values.join(", ");
  }
  const visible = values.slice(0, MAX_VALUES_BEFORE_OVERFLOW).join(", ");
  return `${visible} +${values.length - MAX_VALUES_BEFORE_OVERFLOW} more`;
}

function buildDescriptors(filters: AppliedFilters): ChipDescriptor[] {
  const out: ChipDescriptor[] = [];
  // Range filters render as "Field: lo–hi"
  if (filters.yearMin !== null && filters.yearMax !== null) {
    out.push({ dim: "year", label: "Year", body: `${filters.yearMin}–${filters.yearMax}` });
  }
  // Multi-value filters apply comma-collapse + 3-truncate
  if (filters.caseType.length > 0) {
    out.push({
      dim: "caseType",
      label: "Case type",
      body: multiValueBody(filters.caseType.map(humanizeCaseType)),
    });
  }
  // Single-value filters render as "Field: value"
  if (filters.city !== null) {
    out.push({ dim: "city", label: "City", body: filters.city });
  }
  if (filters.victimGender.length > 0) {
    out.push({ dim: "victimGender", label: "Gender", body: multiValueBody(filters.victimGender) });
  }
  if (filters.victimRace.length > 0) {
    out.push({ dim: "victimRace", label: "Race", body: multiValueBody(filters.victimRace) });
  }
  if (filters.weapon.length > 0) {
    out.push({ dim: "weapon", label: "Weapon", body: multiValueBody(filters.weapon) });
  }
  if (filters.locationType.length > 0) {
    out.push({ dim: "locationType", label: "Location", body: multiValueBody(filters.locationType) });
  }
  if (filters.sourceSystem.length > 0) {
    out.push({
      dim: "sourceSystem",
      label: "Source",
      body: multiValueBody(filters.sourceSystem.map((s) => s.name)),
    });
  }
  if (filters.precision.length > 0) {
    out.push({ dim: "precision", label: "Precision", body: multiValueBody(filters.precision) });
  }
  return out;
}

/**
 * Chip strip rendered above /cold-cases and /cold-cases/map.
 * One chip per applied dimension. Range filters render as "Field: lo–hi";
 * single-value as "Field: value"; multi-value with comma-collapse +
 * 3-truncate. Hidden when no filters are active.
 *
 * Critical for transparency: when a user filters by weapon=unknown the
 * matching cards have no weapon badge per the hide-unknown rule. The
 * chip "Weapon: unknown" is the only signal explaining the absence.
 */
export function AppliedFilterChips({
  filters,
  onClearDimension,
  onClearAll,
}: AppliedFilterChipsProps) {
  const descriptors = buildDescriptors(filters);
  if (descriptors.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      role="region"
      aria-label="Applied filters"
    >
      {descriptors.map((d) => (
        <span
          key={d.dim}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-elev py-1 pl-2.5 pr-1.5 font-mono text-2xs"
        >
          <span>
            <span className="text-faint">{d.label}:</span>{" "}
            <span className="text-foreground">{d.body}</span>
          </span>
          <button
            type="button"
            aria-label={`Clear ${d.label.toLowerCase()} filter`}
            onClick={() => {
              track("filter_cleared", { scope: "single" });
              onClearDimension(d.dim);
            }}
            className="rounded p-0.5 text-faint transition-colors hover:text-primary"
          >
            <XIcon className="size-2.5" />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={() => {
          track("filter_cleared", { scope: "all" });
          onClearAll();
        }}
        className="ml-0.5 font-mono text-2xs text-faint underline-offset-2 transition-colors hover:text-foreground hover:underline"
      >
        Clear all
      </button>
    </div>
  );
}
