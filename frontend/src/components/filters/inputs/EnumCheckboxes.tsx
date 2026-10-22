"use client";

import { FilterFieldset } from "./FilterFieldset";
import { FilterOptionRow } from "./FilterOptionRow";

export interface EnumCheckboxesProps {
  legend: string;
  options: string[];
  selected: string[];
  counts?: Record<string, number>;
  onChange: (value: string[]) => void;
}

/**
 * Generic multi-select checkbox group for string enums (weapon,
 * location_type, future Tier 2 enum filters). Renders nothing when
 * options is empty, matching the existing input pattern.
 */
export function EnumCheckboxes({
  legend,
  options,
  selected,
  counts,
  onChange,
}: EnumCheckboxesProps) {
  if (options.length === 0) return null;

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <FilterFieldset legend={legend}>
      {options.map((opt) => (
        <FilterOptionRow
          key={opt}
          label={opt}
          ariaLabel={opt}
          checked={selected.includes(opt)}
          count={counts?.[opt]}
          onToggle={() => toggle(opt)}
        />
      ))}
    </FilterFieldset>
  );
}
