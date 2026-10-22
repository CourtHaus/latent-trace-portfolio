"use client";

import { useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryState, parseAsInteger } from "nuqs";
import Link from "next/link";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { FilterSidebar } from "@/components/filters/FilterSidebar";
import { PendingVeil } from "@/components/PendingVeil";
import { AppliedFilterChips, type AppliedFilterDimension } from "@/components/AppliedFilterChips";
import { filterUrlParsers } from "@/lib/filterUrlState";
import { RecordStrip } from "./RecordStrip";
import { SortSelect } from "./SortSelect";
import { SearchBar } from "./SearchBar";
import type { components } from "@/lib/api-types";
import type { FilterOptions } from "@/lib/getFilterOptions";
import type { FacetCountMaps } from "@/lib/getFacetCounts";

type ColdCaseListItem = components["schemas"]["ColdCaseListItem"];

export interface ListClientProps {
  rows: ColdCaseListItem[];
  filterOptions: FilterOptions;
  /** Per-facet case counts for the rail; null when the count fetch failed. */
  facetCounts: FacetCountMaps | null;
  totalFiltered: number;
  totalUnfiltered: number;
}

export function ListClient({
  rows,
  filterOptions,
  facetCounts,
  totalFiltered,
  totalUnfiltered,
}: ListClientProps) {
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  const pathname = usePathname();

  const [yearMin, setYearMin] = useQueryState("year_min", filterUrlParsers.year_min);
  const [yearMax, setYearMax] = useQueryState("year_max", filterUrlParsers.year_max);
  const [caseType, setCaseType] = useQueryState("case_type", filterUrlParsers.case_type);
  const [city, setCity] = useQueryState("city", filterUrlParsers.city);
  const [gender, setGender] = useQueryState("gender", filterUrlParsers.gender);
  const [race, setRace] = useQueryState("race", filterUrlParsers.race);
  const [weapon, setWeapon] = useQueryState("weapon", filterUrlParsers.weapon);
  const [locationType, setLocationType] = useQueryState("location_type", filterUrlParsers.location_type);
  const [sourceSystem, setSourceSystem] = useQueryState(
    "source_system",
    filterUrlParsers.source_system,
  );
  const [precision, setPrecision] = useQueryState("precision", filterUrlParsers.precision);
  const [q, setQ] = useQueryState("q", filterUrlParsers.q);
  const [sort, setSort] = useQueryState("sort", filterUrlParsers.sort);
  const [, setPage] = useQueryState("page", parseAsInteger);

  const writeOpts = { history: "replace" as const, shallow: false };

  const handleYearRangeChange = (value: { yearMin: number | null; yearMax: number | null }) => {
    startTransition(() => {
      setYearMin(value.yearMin, writeOpts);
      setYearMax(value.yearMax, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleCaseTypeChange = (value: string[]) => {
    startTransition(() => {
      setCaseType(value.length === 0 ? null : value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleCityChange = (value: string | null) => {
    startTransition(() => {
      setCity(value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleGenderChange = (value: string[]) => {
    startTransition(() => {
      setGender(value.length === 0 ? null : value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleRaceChange = (value: string[]) => {
    startTransition(() => {
      setRace(value.length === 0 ? null : value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleWeaponChange = (value: string[]) => {
    startTransition(() => {
      setWeapon(value.length === 0 ? null : value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleLocationTypeChange = (value: string[]) => {
    startTransition(() => {
      setLocationType(value.length === 0 ? null : value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleSourceSystemChange = (value: string[]) => {
    startTransition(() => {
      setSourceSystem(value.length === 0 ? null : value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handlePrecisionChange = (value: string[]) => {
    startTransition(() => {
      setPrecision(value.length === 0 ? null : value, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleSearchChange = (next: string | null) => {
    startTransition(() => {
      setQ(next, writeOpts);
      setPage(null, writeOpts);
    });
  };
  const handleSortChange = (next: string) => {
    startTransition(() => {
      // Default sort -> clear param (cleaner URLs)
      setSort(next === "incident_date_desc" ? null : (next as typeof sort), writeOpts);
      setPage(null, writeOpts);
    });
  };

  const handleResetFilters = () => {
    // Single router.replace instead of 9 individual nuqs setters. The
    // multi-setter approach raced inside nuqs's useOptimistic queue —
    // some checkboxes' URL params would clear, others wouldn't, and the
    // checkbox UI desynced from the URL because the optimistic snapshots
    // only saw the LAST setter's state. One atomic navigation fixes it
    // and is also less wasteful (one router transition, not 9).
    startTransition(() => {
      router.replace(pathname, { scroll: false });
    });
  };

  const handleClearDimension = (dim: AppliedFilterDimension) => {
    startTransition(() => {
      switch (dim) {
        case "year":
          setYearMin(null, writeOpts);
          setYearMax(null, writeOpts);
          break;
        case "caseType":
          setCaseType(null, writeOpts);
          break;
        case "city":
          setCity(null, writeOpts);
          break;
        case "victimGender":
          setGender(null, writeOpts);
          break;
        case "victimRace":
          setRace(null, writeOpts);
          break;
        case "weapon":
          setWeapon(null, writeOpts);
          break;
        case "locationType":
          setLocationType(null, writeOpts);
          break;
        case "sourceSystem":
          setSourceSystem(null, writeOpts);
          break;
        case "precision":
          setPrecision(null, writeOpts);
          break;
      }
      setPage(null, writeOpts);
    });
  };

  const sidebarProps = {
    title: "Cold Cases",
    isPending,
    counts: facetCounts ?? undefined,
    caseTypeOptions: filterOptions.case_types,
    cityOptions: filterOptions.cities,
    victimGenderOptions: filterOptions.genders,
    victimRaceOptions: filterOptions.races,
    weaponOptions: filterOptions.weapons,
    locationTypeOptions: filterOptions.location_types,
    sourceSystemOptions: filterOptions.source_systems,
    yearBounds: filterOptions.year_range,
    yearMin,
    yearMax,
    caseType: caseType ?? [],
    city,
    victimGender: gender ?? [],
    victimRace: race ?? [],
    weapon: weapon ?? [],
    locationType: locationType ?? [],
    sourceSystem: sourceSystem ?? [],
    precision: precision ?? [],
    onYearRangeChange: handleYearRangeChange,
    onCaseTypeChange: handleCaseTypeChange,
    onCityChange: handleCityChange,
    onVictimGenderChange: handleGenderChange,
    onVictimRaceChange: handleRaceChange,
    onWeaponChange: handleWeaponChange,
    onLocationTypeChange: handleLocationTypeChange,
    onSourceSystemChange: handleSourceSystemChange,
    onPrecisionChange: handlePrecisionChange,
    onResetFilters: handleResetFilters,
    footerSlot: (
      <>
        {totalUnfiltered} cases in the dataset.{" "}
        <Link href="/cold-cases/map" className="underline">
          View on map
        </Link>
        .
      </>
    ),
  };

  return (
    <div className="relative flex gap-6">
      {/* Desktop sidebar */}
      <FilterSidebar {...sidebarProps} className="hidden lg:flex" />

      <main className="min-w-0 flex-1 pt-1">
        {/* Mobile filters trigger — in normal flow above the toolbar so it no
            longer overlaps the applied-filter chips / controls. */}
        <div className="mb-3 lg:hidden">
          <Sheet>
            <SheetTrigger
              aria-label="Open filters"
              className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground"
            >
              <Menu className="size-4" aria-hidden="true" /> Filters
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-0">
              <SheetTitle className="sr-only">Cold Cases Filters</SheetTitle>
              <FilterSidebar {...sidebarProps} />
            </SheetContent>
          </Sheet>
        </div>

        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
          <div className="min-w-0 flex-1">
            <AppliedFilterChips
              filters={{
                yearMin,
                yearMax,
                caseType: caseType ?? [],
                city,
                victimGender: gender ?? [],
                victimRace: race ?? [],
                weapon: weapon ?? [],
                locationType: locationType ?? [],
                sourceSystem: (sourceSystem ?? []).map((code) => {
                  const found = filterOptions.source_systems.find((s) => s.code === code);
                  return { code, name: found?.name ?? code };
                }),
                precision: precision ?? [],
              }}
              onClearDimension={handleClearDimension}
              onClearAll={handleResetFilters}
            />
          </div>
          <div className="flex w-full items-center gap-2 sm:w-auto sm:shrink-0">
            <SortSelect value={sort ?? "incident_date_desc"} onChange={handleSortChange} />
            <SearchBar value={q} onChange={handleSearchChange} isPending={isPending} />
          </div>
        </div>
        {totalFiltered === 0 ? (
          <div className="text-center py-16">
            <h2 className="text-lg font-semibold mb-2">No cases match these filters</h2>
            <p className="text-muted-foreground mb-4">
              Try broadening your selections.
            </p>
            <Button variant="outline" onClick={handleResetFilters}>
              Reset filters
            </Button>
          </div>
        ) : (
          <PendingVeil isPending={isPending}>
            <div className="flex flex-col gap-1.5">
              {rows.map((row) => (
                <RecordStrip key={row.case_id} row={row} />
              ))}
            </div>
          </PendingVeil>
        )}
      </main>
    </div>
  );
}
