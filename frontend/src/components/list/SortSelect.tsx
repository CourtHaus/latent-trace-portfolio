"use client";

import { ChevronDown } from "lucide-react";
import { SORT_OPTIONS, type SortOrder } from "@/lib/sortOrder";

export function SortSelect({
  value,
  onChange,
}: {
  value: SortOrder;
  onChange: (next: SortOrder) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 font-mono text-2xs text-faint focus-within:border-faint">
      <span>sort</span>
      <select
        name="sort"
        aria-label="Sort cases"
        value={value}
        onChange={(e) => onChange(e.target.value as SortOrder)}
        className="cursor-pointer appearance-none bg-transparent pr-1 font-mono text-2xs text-foreground focus:outline-none"
      >
        {SORT_OPTIONS.map((o) => (
          <option key={o.value} value={o.value} className="bg-card text-foreground">
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="size-3 text-accent" aria-hidden="true" />
    </label>
  );
}
