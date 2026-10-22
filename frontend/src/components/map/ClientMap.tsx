"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryState } from "nuqs";
import { mapUrlParsers } from "@/lib/mapUrlState";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Menu } from "lucide-react";
import { FilterSidebar } from "@/components/filters/FilterSidebar";
import { PendingVeil } from "@/components/PendingVeil";
import { AppliedFilterChips, type AppliedFilterDimension } from "@/components/AppliedFilterChips";
import { MapLoadingFallback } from "./MapLoadingFallback";
import { MapEmptyOverlay } from "./MapEmptyOverlay";
import Link from "next/link";
import type { components } from "@/lib/api-types";
import type { FilterOptions } from "@/lib/getFilterOptions";
import type { FacetCountMaps } from "@/lib/getFacetCounts";

type ColdCaseMapItem = components["schemas"]["ColdCaseMapItem"];
type ColdCaseMapClusterItem = components["schemas"]["ColdCaseMapClusterItem"];
type MapMode = components["schemas"]["ColdCaseMapResponse"]["mode"];

const MapLeaflet = dynamic(
  () => import("./MapLeaflet").then((m) => m.MapLeaflet),
  {
    ssr: false,
    loading: () => <MapLoadingFallback />,
  },
);

export interface ClientMapProps {
  /**
   * Server-decided render mode. `clusters` at low zoom (aggregated grid
   * cells), `points` at high zoom (individual cases). The server picks
   * based on the `zoom` URL param.
   */
  initialMode: MapMode;
  initialData: ColdCaseMapItem[];
  initialClusters: ColdCaseMapClusterItem[];
  /**
   * Pre-computed filter option lists from the server (unfiltered scope).
   * Replaces the old `allMapCases` prop — options no longer need to be
   * derived client-side from a full unfiltered dataset download.
   */
  filterOptions: FilterOptions;
  /** Per-facet counts for the rail; null when the count fetch failed. */
  facetCounts: FacetCountMaps | null;
  totalAll: number;
  initialBbox: [number, number, number, number] | null;
  initialZoom: number;
  /** Geocoded (mapped) case count for the current filter scope; null when the facet-count fetch failed. */
  mapped?: number | null;
  /** Total in the current filter scope (geocoded + ungeocoded). */
  coverageTotal?: number;
  /** coverageTotal - mapped; null when mapped is null. */
  unresolved?: number | null;
}

export function ClientMap({
  initialMode,
  initialData,
  initialClusters,
  filterOptions,
  facetCounts,
  totalAll,
  initialBbox,
  initialZoom,
  mapped = null,
  coverageTotal,
  unresolved = null,
}: ClientMapProps) {
  const [isPending, startTransition] = useTransition();
  const [recenterToken, setRecenterToken] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerTriggerRef = useRef<HTMLButtonElement>(null);
  const drawerCloseRef = useRef<HTMLButtonElement>(null);
  const drawerWasOpen = useRef(false);

  // Desktop filter drawer focus management. The mobile path uses the Sheet
  // primitive (which traps + restores focus itself); the desktop in-stage
  // drawer is a plain element, so we manage it here: move focus in on open,
  // trap Tab within it, Esc to close, and restore focus to the trigger on
  // close (the trigger remounts when filtersOpen flips false, so this effect —
  // running post-commit — sees the fresh ref).
  useEffect(() => {
    if (filtersOpen) {
      drawerWasOpen.current = true;
      drawerCloseRef.current?.focus();
      const onKey = (e: KeyboardEvent) => {
        if (e.key === "Escape") {
          setFiltersOpen(false);
          return;
        }
        if (e.key !== "Tab") return;
        const drawer = drawerRef.current;
        if (!drawer) return;
        // Drawer is `hidden lg:block`; below lg it's display:none (offsetParent
        // null). Don't trap Tab when it isn't actually visible — that would
        // strand keyboard users on the now-visible mobile controls.
        if (drawer.offsetParent === null) return;
        const focusables = drawer.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (!first || !last) return;
        const active = document.activeElement;
        if (active && !drawer.contains(active)) {
          // Focus escaped the drawer (e.g. into the map) — pull it back in.
          e.preventDefault();
          first.focus();
        } else if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
    if (drawerWasOpen.current) {
      drawerWasOpen.current = false;
      drawerTriggerRef.current?.focus();
    }
  }, [filtersOpen]);

  // The desktop drawer only exists at lg+. If the viewport drops below lg while
  // it's open (resize / tablet rotation), close it — otherwise it's display:none
  // but still "open", hiding the title + mobile trigger (the header is sr-only
  // while open) and leaving the focus trap running on a hidden element.
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(min-width: 64rem)");
    const onChange = () => {
      if (!mq.matches) setFiltersOpen(false);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const router = useRouter();
  const pathname = usePathname();

  const [bbox, setBbox] = useQueryState("bbox", mapUrlParsers.bbox);
  const [zoom, setZoom] = useQueryState("zoom", mapUrlParsers.zoom);
  const [yearMin, setYearMin] = useQueryState("year_min", mapUrlParsers.year_min);
  const [yearMax, setYearMax] = useQueryState("year_max", mapUrlParsers.year_max);
  const [caseType, setCaseType] = useQueryState("case_type", mapUrlParsers.case_type);
  const [city, setCity] = useQueryState("city", mapUrlParsers.city);
  const [gender, setGender] = useQueryState("gender", mapUrlParsers.gender);
  const [race, setRace] = useQueryState("race", mapUrlParsers.race);
  const [weapon, setWeapon] = useQueryState("weapon", mapUrlParsers.weapon);
  const [locationType, setLocationType] = useQueryState("location_type", mapUrlParsers.location_type);
  const [sourceSystem, setSourceSystem] = useQueryState(
    "source_system",
    mapUrlParsers.source_system,
  );
  const [precision, setPrecision] = useQueryState("precision", mapUrlParsers.precision);

  const activeFilterCount =
    (yearMin != null || yearMax != null ? 1 : 0) +
    (caseType?.length ? 1 : 0) +
    (city ? 1 : 0) +
    (gender?.length ? 1 : 0) +
    (race?.length ? 1 : 0) +
    (weapon?.length ? 1 : 0) +
    (locationType?.length ? 1 : 0) +
    (sourceSystem?.length ? 1 : 0) +
    (precision?.length ? 1 : 0);

  const total = coverageTotal ?? totalAll;

  // bbox/zoom drive the server fetch via URL state. bbox is also read in
  // handleRecenter; zoom is shown in the stat chip overlay. MapLeaflet takes
  // initialBbox/zoom (SSR-set) and reports viewport changes back through the setters.

  // moveend → commit bbox + zoom to the URL together. Both shallow:false so
  // the server refetches: zoom decides cluster vs point mode, bbox scopes it.
  const handleViewportChange = (nextBbox: string, nextZoom: number) => {
    startTransition(() => {
      setBbox(nextBbox, { scroll: false, history: "replace", shallow: false });
      setZoom(nextZoom, { scroll: false, history: "replace", shallow: false });
    });
  };

  const handleYearRangeChange = (value: { yearMin: number | null; yearMax: number | null }) => {
    startTransition(() => {
      setYearMin(value.yearMin, { history: "replace", shallow: false });
      setYearMax(value.yearMax, { history: "replace", shallow: false });
    });
  };

  const handleCaseTypeChange = (value: string[]) => {
    startTransition(() => {
      setCaseType(value.length === 0 ? null : value, { history: "replace", shallow: false });
    });
  };

  const handleCityChange = (value: string | null) => {
    startTransition(() => {
      setCity(value, { history: "replace", shallow: false });
    });
  };

  const handleGenderChange = (value: string[]) => {
    startTransition(() => {
      setGender(value.length === 0 ? null : value, { history: "replace", shallow: false });
    });
  };

  const handleRaceChange = (value: string[]) => {
    startTransition(() => {
      setRace(value.length === 0 ? null : value, { history: "replace", shallow: false });
    });
  };

  const handleWeaponChange = (value: string[]) => {
    startTransition(() => {
      setWeapon(value.length === 0 ? null : value, { history: "replace", shallow: false });
    });
  };

  const handleLocationTypeChange = (value: string[]) => {
    startTransition(() => {
      setLocationType(value.length === 0 ? null : value, { history: "replace", shallow: false });
    });
  };

  const handleSourceSystemChange = (value: string[]) => {
    startTransition(() => {
      setSourceSystem(
        value.length === 0 ? null : value,
        { history: "replace", shallow: false },
      );
    });
  };

  const handlePrecisionChange = (value: string[]) => {
    startTransition(() => {
      setPrecision(
        value.length === 0 ? null : value,
        { history: "replace", shallow: false },
      );
    });
  };

  const handleResetFilters = () => {
    // Single router.replace instead of 8 individual nuqs setters. The
    // multi-setter approach raced inside nuqs's useOptimistic queue —
    // checkboxes' URL params would clear but the React tree re-read a
    // stale optimistic snapshot, leaving boxes visually checked even
    // though the data filter cleared. One atomic navigation fixes it
    // and is also less wasteful (one router transition, not 8).
    //
    // Bbox preserved — viewport state isn't a "filter" in the user's
    // mental model; reset clears narrow-down filters but keeps where
    // they're looking.
    startTransition(() => {
      const params = new URLSearchParams();
      if (bbox) params.set("bbox", bbox);
      if (zoom != null) params.set("zoom", String(zoom));
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    });
  };

  const handleClearDimension = (dim: AppliedFilterDimension) => {
    startTransition(() => {
      const opts = { history: "replace" as const, shallow: false };
      switch (dim) {
        case "year":
          setYearMin(null, opts);
          setYearMax(null, opts);
          break;
        case "caseType":
          setCaseType(null, opts);
          break;
        case "city":
          setCity(null, opts);
          break;
        case "victimGender":
          setGender(null, opts);
          break;
        case "victimRace":
          setRace(null, opts);
          break;
        case "weapon":
          setWeapon(null, opts);
          break;
        case "locationType":
          setLocationType(null, opts);
          break;
        case "sourceSystem":
          setSourceSystem(null, opts);
          break;
        case "precision":
          setPrecision(null, opts);
          break;
      }
    });
  };

  const handleRecenter = () => {
    // Recenter sequence:
    //   1. Clear bbox from URL.
    //   2. Increment recenterToken → MapLeaflet's useEffect flyTo(DEFAULT_CENTER).
    //   3. flyTo's moveend listener commits the resulting viewport back to URL.
    //
    // Net: URL briefly has no bbox, then gets re-populated with the default view's
    // bbox. This is intentional — every viewport change (pan, zoom, recenter) writes
    // the resulting bbox to URL so back-nav can restore any prior view, including
    // the default. The transient "no bbox" state is invisible to users; the URL is
    // a side-effect of viewport state, not a driver of it.
    startTransition(() => {
      setBbox(null, { scroll: false, history: "replace", shallow: false });
      setZoom(null, { scroll: false, history: "replace", shallow: false });
    });
    setRecenterToken((n) => n + 1);
  };

  const shouldFitBounds = initialBbox === null;

  // "Cases in view" for the sidebar header. In point mode it's the rows
  // rendered; in cluster mode it's the sum of the aggregated cell counts.
  const visibleCount =
    initialMode === "clusters"
      ? initialClusters.reduce((sum, c) => sum + c.count, 0)
      : initialData.length;

  const sidebarProps = {
    title: "Cold Case Map",
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
  };

  return (
    <div className="relative h-[calc(100dvh-86px)] min-h-[520px] w-full overflow-hidden bg-inset">
      {/* Map fills the stage */}
      <div className="absolute inset-0">
        <PendingVeil isPending={isPending} dim={false} className="absolute inset-0 flex flex-col">
          <MapLeaflet
            mode={initialMode}
            data={initialData}
            clusters={initialClusters}
            initialBbox={initialBbox}
            initialZoom={initialZoom}
            shouldFitBounds={shouldFitBounds}
            onViewportChange={handleViewportChange}
            onRecenterToken={recenterToken}
          />
          {!isPending && visibleCount === 0 && (
            <MapEmptyOverlay onReset={handleResetFilters} onRecenter={handleRecenter} />
          )}
        </PendingVeil>
      </div>

      {/* Title block + collapsed Filters trigger (top-left). Hidden while the
          desktop drawer is open so they never overlap. */}
      <header
        className={
          filtersOpen
            ? "sr-only"
            : "pointer-events-none absolute left-4 top-4 z-[1000] max-w-[min(440px,calc(100%-2rem))]"
        }
      >
        <p className="font-mono text-2xs uppercase tracking-eyebrow text-accent [text-shadow:0_1px_10px_rgba(0,0,0,0.85)]">
          Geographic distribution
        </p>
        <h1 className="mt-1.5 font-headline text-3xl font-medium tracking-tight text-foreground [text-shadow:0_2px_24px_rgba(0,0,0,0.7)]">
          The case map
        </h1>
        <p className="mt-2 font-mono text-xs tracking-snug text-muted-foreground [text-shadow:0_1px_10px_rgba(0,0,0,0.85)]">
          {mapped != null ? (
            <>
              <span className="text-primary">
                {mapped.toLocaleString()} of {total.toLocaleString()} mapped
              </span>{" "}
              · {(unresolved ?? 0).toLocaleString()} unresolved · same filters as the register
            </>
          ) : (
            <>
              <span className="text-primary">{total.toLocaleString()} records</span> · same filters as
              the register
            </>
          )}
        </p>

        {/* Desktop trigger → in-stage drawer. Gated so no focusable control
            hides behind sr-only when the drawer is open. */}
        {!filtersOpen && (
          <button
            ref={drawerTriggerRef}
            type="button"
            onClick={() => setFiltersOpen(true)}
            aria-haspopup="dialog"
            className="pointer-events-auto mt-3.5 hidden items-center gap-2 rounded-md border border-border bg-card/85 px-3 py-2 font-mono text-2xs uppercase tracking-eyebrow text-foreground backdrop-blur transition-colors hover:border-primary lg:inline-flex"
          >
            <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" />
            Filters
            {activeFilterCount > 0 && <span className="text-faint">· {activeFilterCount} active</span>}
          </button>
        )}

        {/* Mobile trigger + Sheet. Lives INSIDE the header flow (not a separate
            absolute anchor) so it stacks under the title instead of painting
            over the eyebrow/h1 at the shared left-4/top-4 corner on small
            screens. */}
        <div className="pointer-events-auto mt-3.5 lg:hidden">
          <Sheet>
            <SheetTrigger
              aria-label="Open filters"
              className="inline-flex items-center gap-2 rounded-md border border-border bg-card/85 px-3 py-2 font-mono text-2xs uppercase tracking-eyebrow text-foreground backdrop-blur"
            >
              <Menu className="size-3.5" aria-hidden="true" /> Filters
              {activeFilterCount > 0 && <span className="text-faint">· {activeFilterCount}</span>}
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-0">
              <SheetTitle className="sr-only">Cold Case Map Filters</SheetTitle>
              <FilterSidebar {...sidebarProps} />
            </SheetContent>
          </Sheet>
        </div>
      </header>

      {/* Desktop filter drawer (top-left, over the title) */}
      {filtersOpen && (
        <div
          ref={drawerRef}
          id="map-filter-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="Map filters"
          className="absolute left-4 top-4 z-[1001] hidden w-60 lg:block"
        >
          <div className="mb-1.5 flex justify-end">
            <button
              ref={drawerCloseRef}
              type="button"
              aria-label="Close filters"
              onClick={() => setFiltersOpen(false)}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card/85 px-2.5 py-1 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground backdrop-blur transition-colors hover:text-foreground"
            >
              <span aria-hidden="true">✕</span> Close
            </button>
          </div>
          <FilterSidebar {...sidebarProps} className="max-h-[calc(100dvh-150px)]" />
        </div>
      )}

      {/* Applied filter chips: anchored in the gap between the top-left title
          (<= ~28rem wide) and the top-right stat chips (~14rem), and only at
          lg+ where that gap exists. A viewport-centered strip would slide under
          the wide title; below lg the filter trigger's "· N" badge conveys
          active filters instead. */}
      <div className="absolute top-4 z-[1000] hidden justify-center lg:left-[29rem] lg:right-56 lg:flex">
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

      {/* Stat chips (top-right) */}
      <div className="absolute right-4 top-4 z-[1000] flex flex-col items-end gap-2">
        {mapped != null && (
          <span className="rounded-md border border-border bg-card/85 px-3 py-1.5 font-mono text-2xs text-muted-foreground backdrop-blur">
            <span className="text-primary tabular-nums">{mapped.toLocaleString()}</span> of{" "}
            {total.toLocaleString()} mapped
          </span>
        )}
        <span className="rounded-md border border-border bg-card/85 px-3 py-1.5 font-mono text-2xs text-muted-foreground backdrop-blur">
          Zoom <span className="tabular-nums">{zoom ?? initialZoom}</span> ·{" "}
          <span className="text-accent"><span aria-hidden="true">●</span> {initialMode === "clusters" ? "Cluster" : "Point"} mode</span>
        </span>
      </div>

      {/* Recenter (bottom-left). bottom-[5.5rem] clears the native Leaflet
          zoom control below it (pinned in globals.css: .leaflet-control-zoom
          margin 16px + ~65px tall). Keep in sync if that control changes. */}
      <button
        type="button"
        onClick={handleRecenter}
        className="absolute bottom-[5.5rem] left-4 z-[1000] inline-flex items-center gap-2 rounded-md border border-border bg-card/85 px-3 py-2 font-mono text-2xs uppercase tracking-eyebrow text-foreground backdrop-blur transition-colors hover:border-primary"
      >
        <span aria-hidden="true">⌖</span> Recenter
      </button>

      {/* Legend (bottom-right) — hidden on mobile to free the bottom strip for
          the full-list link and avoid overlapping it. */}
      <div className="pointer-events-none absolute bottom-4 right-4 z-[1000] hidden rounded-md border border-border bg-card/90 px-3 py-2 backdrop-blur sm:block">
        <div className="mb-1.5 font-mono text-2xs uppercase tracking-eyebrow text-faint">Legend</div>
        <div className="flex items-center gap-2 font-mono text-2xs text-muted-foreground">
          <span className="size-3 shrink-0 rounded-full border border-primary bg-background/55" />
          Cluster · n cases
        </div>
        <div className="mt-1 flex items-center gap-2 font-mono text-2xs text-muted-foreground">
          <span className="size-2.5 shrink-0 rounded-full border-2 border-background bg-primary" />
          Single case · point
        </div>
      </div>

      {/* Link back to the full list (bottom-center). Width-capped so it stays
          within the viewport on mobile and clears the bottom-right legend at
          sm+ (reserving ~12rem each side for it). */}
      <div className="absolute bottom-4 left-1/2 z-[1000] max-w-[calc(100%-2rem)] -translate-x-1/2 rounded-md border border-border bg-card/85 px-3 py-1.5 text-center font-mono text-2xs text-muted-foreground backdrop-blur sm:max-w-[calc(100%-24rem)]">
        Not all {totalAll.toLocaleString()} cases have coordinates.{" "}
        <Link href="/cold-cases" className="text-primary hover:brightness-110">
          See the full list →
        </Link>
      </div>
    </div>
  );
}
