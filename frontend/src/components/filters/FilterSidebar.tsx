"use client";

import type { ReactNode } from "react";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { track } from "@/lib/analytics/client";
import { YearRange, type YearRangeValue, type YearBounds } from "./inputs/YearRange";
import { CaseTypeCheckboxes } from "./inputs/CaseTypeCheckboxes";
import { CityCombobox } from "./inputs/CityCombobox";
import { VictimGenderCheckboxes } from "./inputs/VictimGenderCheckboxes";
import { VictimRaceCheckboxes } from "./inputs/VictimRaceCheckboxes";
import { EnumCheckboxes } from "./inputs/EnumCheckboxes";
import {
  SourceSystemCheckboxes,
  type SourceSystemOption,
} from "./inputs/SourceSystemCheckboxes";
import { MethodologyLink } from "@/components/MethodologyLink";
import { useCollapsibleSections } from "@/lib/useCollapsibleSections";
import type { FacetCountMaps } from "@/lib/getFacetCounts";

const SECTION_IDS = ["source", "case-attrs", "victim", "mo", "precision"] as const;
type SectionId = (typeof SECTION_IDS)[number];

// Sections collapsed on first load (before any stored preference).
const DEFAULT_COLLAPSED_SECTIONS = ["source"] as const;

export interface FilterSidebarProps {
  title: string;
  isPending: boolean;
  caseTypeOptions: string[];
  cityOptions: string[];
  victimGenderOptions: string[];
  victimRaceOptions: string[];
  weaponOptions: string[];
  locationTypeOptions: string[];
  sourceSystemOptions: SourceSystemOption[];
  yearMin: number | null;
  yearMax: number | null;
  caseType: string[];
  city: string | null;
  victimGender: string[];
  victimRace: string[];
  weapon: string[];
  locationType: string[];
  sourceSystem: string[];
  onYearRangeChange: (value: YearRangeValue) => void;
  onCaseTypeChange: (value: string[]) => void;
  onCityChange: (value: string | null) => void;
  onVictimGenderChange: (value: string[]) => void;
  onVictimRaceChange: (value: string[]) => void;
  onWeaponChange: (value: string[]) => void;
  onLocationTypeChange: (value: string[]) => void;
  onSourceSystemChange: (value: string[]) => void;
  precision: string[];
  onPrecisionChange: (value: string[]) => void;
  onResetFilters: () => void;
  headerActions?: ReactNode;
  footerSlot?: ReactNode;
  className?: string;
  yearBounds?: YearBounds;
  /** Per-facet case counts shown beside each option; omitted = no counts. */
  counts?: FacetCountMaps;
}

interface SectionProps {
  id: SectionId;
  title: string;
  isCollapsed: boolean;
  onToggle: () => void;
  headerExtra?: ReactNode;
  children: ReactNode;
}

function Section({ id, title, isCollapsed, onToggle, headerExtra, children }: SectionProps) {
  return (
    <div data-section={id} className="border-b border-hair px-3.5 py-3.5 last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        aria-controls={`section-body-${id}`}
        className="flex w-full items-center justify-between text-left font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground transition-colors hover:text-foreground"
      >
        <span>{title}</span>
        {isCollapsed ? (
          <ChevronRightIcon className="h-3.5 w-3.5 text-faint" />
        ) : (
          <ChevronDownIcon className="h-3.5 w-3.5 text-faint" />
        )}
      </button>
      {headerExtra && !isCollapsed && <div className="mt-2">{headerExtra}</div>}
      {!isCollapsed && (
        <div id={`section-body-${id}`} className="mt-3 space-y-4">
          {children}
        </div>
      )}
    </div>
  );
}

function makeFilterHandler<T>(key: string, handler: (v: T) => void) {
  return (v: T) => {
    track("filter_applied", { filter_key: key });
    handler(v);
  };
}

export function FilterSidebar(props: FilterSidebarProps) {
  const sections = useCollapsibleSections(
    "casesignal.filterSidebar.collapsed",
    SECTION_IDS,
    // Data source lists every state/agency, so it's long; start it folded so
    // it doesn't push the more-used filters below the fold on first load.
    DEFAULT_COLLAPSED_SECTIONS,
  );

  return (
    <aside
      aria-label={props.title}
      className={
        "flex w-full flex-col self-start overflow-hidden rounded-lg border border-border bg-card transition-opacity lg:sticky lg:top-[4.5rem] lg:w-[15rem] lg:shrink-0 " +
        (props.isPending ? "opacity-70 " : "") +
        (props.className ?? "")
      }
      data-testid={props.isPending ? "filter-sidebar-pending" : undefined}
    >
      <div className="flex items-center justify-between border-b border-hair bg-elev px-3.5 py-3 font-mono text-2xs uppercase tracking-eyebrow text-faint">
        <span>Filters</span>
        <button
          type="button"
          onClick={() => {
            track("filter_cleared", { scope: "all" });
            props.onResetFilters();
          }}
          className="text-primary transition-[filter] hover:brightness-110"
        >
          Clear all
        </button>
      </div>

      <div className="overflow-y-auto">
        <Section
          id="source"
          title="Data source"
          isCollapsed={sections.isCollapsed("source")}
          onToggle={() => sections.toggle("source")}
        >
          <SourceSystemCheckboxes
            options={props.sourceSystemOptions}
            selected={props.sourceSystem}
            counts={props.counts?.sourceSystem}
            onChange={makeFilterHandler("sourceSystem", props.onSourceSystemChange)}
          />
        </Section>

        <Section
          id="case-attrs"
          title="Case attributes"
          isCollapsed={sections.isCollapsed("case-attrs")}
          onToggle={() => sections.toggle("case-attrs")}
        >
          <YearRange
            yearMin={props.yearMin}
            yearMax={props.yearMax}
            bounds={props.yearBounds}
            onChange={makeFilterHandler("year", props.onYearRangeChange)}
          />
          <CaseTypeCheckboxes
            options={props.caseTypeOptions}
            selected={props.caseType}
            counts={props.counts?.caseType}
            onChange={makeFilterHandler("caseType", props.onCaseTypeChange)}
          />
          <CityCombobox
            options={props.cityOptions}
            value={props.city}
            onChange={makeFilterHandler("city", props.onCityChange)}
          />
        </Section>

        <Section
          id="victim"
          title="Victim"
          isCollapsed={sections.isCollapsed("victim")}
          onToggle={() => sections.toggle("victim")}
        >
          <VictimGenderCheckboxes
            options={props.victimGenderOptions}
            selected={props.victimGender}
            counts={props.counts?.gender}
            onChange={makeFilterHandler("victimGender", props.onVictimGenderChange)}
          />
          <VictimRaceCheckboxes
            options={props.victimRaceOptions}
            selected={props.victimRace}
            counts={props.counts?.race}
            onChange={makeFilterHandler("victimRace", props.onVictimRaceChange)}
          />
        </Section>

        <Section
          id="mo"
          title="Modus operandi"
          isCollapsed={sections.isCollapsed("mo")}
          onToggle={() => sections.toggle("mo")}
          headerExtra={
            <MethodologyLink section="modus-operandi">
              About these fields →
            </MethodologyLink>
          }
        >
          <EnumCheckboxes
            legend="Weapon"
            options={props.weaponOptions}
            selected={props.weapon}
            counts={props.counts?.weapon}
            onChange={makeFilterHandler("weapon", props.onWeaponChange)}
          />
          <EnumCheckboxes
            legend="Location type"
            options={props.locationTypeOptions}
            selected={props.locationType}
            counts={props.counts?.locationType}
            onChange={makeFilterHandler("locationType", props.onLocationTypeChange)}
          />
        </Section>

        <Section
          id="precision"
          title="Geocoding precision"
          isCollapsed={sections.isCollapsed("precision")}
          onToggle={() => sections.toggle("precision")}
        >
          <EnumCheckboxes
            legend="Precision"
            options={["street", "landmark", "zip", "county"]}
            selected={props.precision}
            counts={props.counts?.precision}
            onChange={makeFilterHandler("precision", props.onPrecisionChange)}
          />
        </Section>

        {props.headerActions && (
          <div className="border-t border-hair px-3.5 py-3">{props.headerActions}</div>
        )}
      </div>

      {props.footerSlot !== undefined && (
        <footer className="border-t border-hair bg-elev px-3.5 py-3 text-2xs text-muted-foreground">
          {props.footerSlot}
        </footer>
      )}
    </aside>
  );
}
