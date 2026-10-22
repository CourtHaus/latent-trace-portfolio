"use client";

import { FilterFieldset } from "./FilterFieldset";
import { FilterOptionRow } from "./FilterOptionRow";

interface Props {
  options: string[];
  selected: string[];
  counts?: Record<string, number>;
  onChange: (value: string[]) => void;
}

export function VictimRaceCheckboxes({ options, selected, counts, onChange }: Props) {
  if (options.length === 0) return null;

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <FilterFieldset legend="Victim race">
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
