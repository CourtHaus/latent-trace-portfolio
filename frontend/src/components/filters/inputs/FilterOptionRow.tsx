"use client";

import type { ReactNode } from "react";
import { Check } from "lucide-react";

export interface FilterOptionRowProps {
  /** Visible label content. */
  label: ReactNode;
  /** Accessible name for the checkbox (falls back to label when it's a string). */
  ariaLabel: string;
  checked: boolean;
  onToggle: () => void;
  /** Optional facet count shown right-aligned (e.g. matches in the corpus). */
  count?: number;
}

/**
 * Instrument-style filter option: a 14px accent checkbox + mono label, with an
 * optional right-aligned facet count. The native input is visually hidden but
 * kept in the a11y tree (sr-only, not display:none) so it stays focusable and
 * exposes the checkbox role + name. The box and count restyle off `peer-checked`.
 */
export function FilterOptionRow({
  label,
  ariaLabel,
  checked,
  onToggle,
  count,
}: FilterOptionRowProps) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2.5 py-1">
      <input
        type="checkbox"
        name={ariaLabel}
        checked={checked}
        onChange={onToggle}
        aria-label={ariaLabel}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className="flex size-[14px] shrink-0 items-center justify-center rounded-[3px] border border-border bg-inset transition-colors peer-checked:border-primary peer-checked:bg-accent-dim peer-checked:[&>svg]:opacity-100 peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-1 peer-focus-visible:ring-offset-background"
      >
        <Check
          className="size-2.5 text-primary opacity-0 transition-opacity"
          strokeWidth={3}
        />
      </span>
      <span className="font-mono text-2xs capitalize text-muted-foreground transition-colors peer-checked:text-foreground">
        {label}
      </span>
      {count !== undefined && (
        <span className="ml-auto font-mono text-2xs tabular-nums text-faint transition-colors peer-checked:text-primary">
          {count.toLocaleString()}
        </span>
      )}
    </label>
  );
}
