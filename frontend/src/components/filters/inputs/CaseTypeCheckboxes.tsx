"use client";

import { humanizeCaseType } from "@/lib/humanizeCaseType";
import { FilterFieldset } from "./FilterFieldset";
import { FilterOptionRow } from "./FilterOptionRow";

interface CaseTypeCheckboxesProps {
  options: string[];
  selected: string[];
  counts?: Record<string, number>;
  onChange: (value: string[]) => void;
}

export function CaseTypeCheckboxes({
  options,
  selected,
  counts,
  onChange,
}: CaseTypeCheckboxesProps) {
  if (options.length === 0) return null;

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <FilterFieldset legend="Case type">
      {options.map((opt) => (
        <FilterOptionRow
          key={opt}
          label={humanizeCaseType(opt)}
          ariaLabel={humanizeCaseType(opt)}
          checked={selected.includes(opt)}
          count={counts?.[opt]}
          onToggle={() => toggle(opt)}
        />
      ))}
    </FilterFieldset>
  );
}
