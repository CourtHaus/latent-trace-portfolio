"use client";

import { useEffect, useRef, useState } from "react";

export interface YearRangeValue {
  yearMin: number | null;
  yearMax: number | null;
}

export interface YearBounds {
  min: number | null;
  max: number | null;
}

interface YearRangeProps extends YearRangeValue {
  onChange: (value: YearRangeValue) => void;
  bounds?: YearBounds;
}

const DEBOUNCE_MS = 150;

export function YearRange({ yearMin, yearMax, onChange, bounds }: YearRangeProps) {
  const [min, setMin] = useState<string>(yearMin?.toString() ?? "");
  const [max, setMax] = useState<string>(yearMax?.toString() ?? "");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const didMountRef = useRef(false);

  const hasNoData = bounds !== undefined && bounds.min === null && bounds.max === null;
  const minPlaceholder = hasNoData
    ? "No dated cases"
    : bounds?.min != null
      ? String(bounds.min)
      : "From";
  const maxPlaceholder = hasNoData
    ? "No dated cases"
    : bounds?.max != null
      ? String(bounds.max)
      : "To";

  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      onChange({
        yearMin: min === "" ? null : Number(min),
        yearMax: max === "" ? null : Number(max),
      });
    }, DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [min, max]);

  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Incident year</legend>
      <div className="flex gap-2">
        <label className="flex-1">
          <span className="sr-only">Minimum year</span>
          <input
            type="number"
            name="year_min"
            inputMode="numeric"
            placeholder={minPlaceholder}
            aria-label="Minimum year"
            value={min}
            disabled={hasNoData}
            onChange={(e) => setMin(e.target.value)}
            className="w-full rounded border px-2 py-1 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </label>
        <label className="flex-1">
          <span className="sr-only">Maximum year</span>
          <input
            type="number"
            name="year_max"
            inputMode="numeric"
            placeholder={maxPlaceholder}
            aria-label="Maximum year"
            value={max}
            disabled={hasNoData}
            onChange={(e) => setMax(e.target.value)}
            className="w-full rounded border px-2 py-1 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </label>
      </div>
    </fieldset>
  );
}
