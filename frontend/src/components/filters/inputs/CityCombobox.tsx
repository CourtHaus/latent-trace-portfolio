"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

interface CityComboboxProps {
  options: string[];
  value: string | null;
  onChange: (value: string | null) => void;
}

const DEBOUNCE_MS = 150;

export function CityCombobox({ options, value, onChange }: CityComboboxProps) {
  const [query, setQuery] = useState(value ?? "");
  const [open, setOpen] = useState(false);
  // Index of the keyboard-highlighted option; -1 = none active.
  const [activeIndex, setActiveIndex] = useState(-1);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const immediate = useRef(false);
  const didMountRef = useRef(false);
  const listboxId = useId();
  const optionId = (i: number) => `${listboxId}-opt-${i}`;

  // Sync the controlled `value` prop into the internal `query` state when
  // the parent changes it externally (e.g. clear-all filters). React's
  // documented "store previous prop, update during render if changed"
  // pattern — fires only when the prop differs from what we already saw,
  // and avoids the cascading-render hit of doing this in an effect.
  // See: https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) {
    setPrevValue(value);
    setQuery(value ?? "");
  }

  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    if (immediate.current) {
      immediate.current = false;
      onChange(query === "" ? null : query);
      return;
    }
    timer.current = setTimeout(() => {
      onChange(query === "" ? null : query);
    }, DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const filtered = useMemo(() => {
    if (!query) return options.slice(0, 10);
    const lower = query.toLowerCase();
    return options.filter((c) => c.toLowerCase().includes(lower)).slice(0, 10);
  }, [query, options]);

  function select(city: string) {
    immediate.current = true;
    setQuery(city);
    setOpen(false);
    setActiveIndex(-1);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (open) setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      const choice = open && activeIndex >= 0 ? filtered[activeIndex] : undefined;
      if (choice !== undefined) {
        e.preventDefault();
        select(choice);
      }
    } else if (e.key === "Tab") {
      // Commit the highlighted option when tabbing away (parity with Enter),
      // so keyboard selection isn't lost to the blur-close timer.
      const choice = filtered[activeIndex];
      if (open && activeIndex >= 0 && choice !== undefined) {
        select(choice);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  const showList = open && filtered.length > 0;

  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">City</legend>
      <div className="relative">
        <input
          name="city"
          aria-label="City"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            showList && activeIndex >= 0 ? optionId(activeIndex) : undefined
          }
          placeholder="All cities"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActiveIndex(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 100)}
          onKeyDown={handleKeyDown}
          className="w-full rounded border px-2 py-1 text-sm"
        />
        {showList && (
          <ul
            id={listboxId}
            role="listbox"
            className="absolute z-10 mt-1 w-full rounded border bg-background shadow-md max-h-48 overflow-auto"
          >
            {filtered.map((c, i) => (
              <li
                key={c}
                id={optionId(i)}
                role="option"
                aria-selected={i === activeIndex}
                className={`px-2 py-1 text-sm cursor-pointer ${
                  i === activeIndex ? "bg-muted" : "hover:bg-muted"
                }`}
                onMouseDown={(e) => {
                  // Prevent input blur from firing before onClick
                  e.preventDefault();
                }}
                onClick={() => select(c)}
              >
                {c}
              </li>
            ))}
          </ul>
        )}
      </div>
    </fieldset>
  );
}
