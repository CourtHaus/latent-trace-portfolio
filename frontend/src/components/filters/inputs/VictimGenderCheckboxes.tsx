"use client";

import { FilterFieldset } from "./FilterFieldset";
import { FilterOptionRow } from "./FilterOptionRow";
import { humanizeGender } from "@/lib/humanizeGender";

interface Props {
  options: string[];
  selected: string[];
  counts?: Record<string, number>;
  onChange: (value: string[]) => void;
}

export function VictimGenderCheckboxes({ options, selected, counts, onChange }: Props) {
  if (options.length === 0) return null;

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <FilterFieldset legend="Victim gender">
      {options.map((opt) => {
        // Display a humanized label (M -> Male); the value/toggle stays raw.
        const label = humanizeGender(opt) ?? opt;
        return (
          <FilterOptionRow
            key={opt}
            label={label}
            ariaLabel={label}
            checked={selected.includes(opt)}
            count={counts?.[opt]}
            onToggle={() => toggle(opt)}
          />
        );
      })}
    </FilterFieldset>
  );
}
