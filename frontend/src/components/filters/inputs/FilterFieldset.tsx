import type { ReactNode } from "react";

/**
 * Sub-group wrapper inside a filter Section: a small legend over a stack of
 * FilterOptionRows. Distinct from the Section header (mono uppercase faint) —
 * this is the second level of hierarchy, so it reads as a quieter sub-label.
 */
export function FilterFieldset({
  legend,
  children,
}: {
  legend: string;
  children: ReactNode;
}) {
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-xs font-medium text-muted-foreground">{legend}</legend>
      <div className="space-y-0.5">{children}</div>
    </fieldset>
  );
}
