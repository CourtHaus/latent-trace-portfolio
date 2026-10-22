"use client";

import { FilterFieldset } from "./FilterFieldset";
import { FilterOptionRow } from "./FilterOptionRow";

export interface SourceSystemOption {
  code: string;
  name: string;
}

export interface SourceSystemCheckboxesProps {
  options: SourceSystemOption[];
  selected: string[];
  counts?: Record<string, number>;
  onChange: (codes: string[]) => void;
}

/**
 * Checkbox group for the source_system filter dimension.
 *
 * Distinct from EnumCheckboxes because the user-visible label
 * (e.g. "Baltimore County PD") differs from the URL-encoded code
 * (BCOUNTY_MD_PD); we toggle by code but display by name.
 */
export function SourceSystemCheckboxes({
  options,
  selected,
  counts,
  onChange,
}: SourceSystemCheckboxesProps) {
  if (options.length === 0) return null;

  const toggle = (code: string) => {
    if (selected.includes(code)) {
      onChange(selected.filter((v) => v !== code));
    } else {
      onChange([...selected, code]);
    }
  };

  return (
    <FilterFieldset legend="Source">
      {options.map((opt) => (
        <FilterOptionRow
          key={opt.code}
          label={opt.name}
          ariaLabel={opt.name}
          checked={selected.includes(opt.code)}
          count={counts?.[opt.code]}
          onToggle={() => toggle(opt.code)}
        />
      ))}
    </FilterFieldset>
  );
}
