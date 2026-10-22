"use client";

import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";

interface Props {
  value: string | null;
  onChange: (next: string | null) => void;
  isPending: boolean;
}

const DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 2;

export function SearchBar({ value, onChange, isPending }: Props) {
  const [local, setLocal] = useState(value ?? "");
  const inputRef = useRef<HTMLInputElement>(null);
  // Track last-seen URL value; when it changes externally (back/forward nav),
  // re-sync local. Computed at render time so we avoid the
  // setState-inside-effect anti-pattern flagged by react-hooks/set-state-in-effect.
  const [lastValue, setLastValue] = useState<string | null>(value);
  if (value !== lastValue) {
    setLastValue(value);
    setLocal(value ?? "");
  }

  // Debounced commit
  useEffect(() => {
    const trimmed = local.trim();
    const next = trimmed.length >= MIN_QUERY_LENGTH ? trimmed : null;
    if (next === value) return;
    const t = setTimeout(() => onChange(next), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [local, value, onChange]);

  // "/" focuses the search, unless the user is already typing somewhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-card px-3 py-2 transition-colors focus-within:border-faint sm:min-w-[14rem] sm:flex-none">
      <Search className="size-3.5 shrink-0 text-faint" aria-hidden="true" />
      <input
        ref={inputRef}
        type="search"
        name="q"
        placeholder="Search ID, name, location…"
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        className="w-full bg-transparent font-mono text-xs text-foreground placeholder:text-faint focus:outline-none [&::-webkit-search-cancel-button]:hidden"
        aria-label="Search cold cases"
      />
      {isPending ? (
        <span className="shrink-0 text-2xs text-faint" aria-hidden="true">
          …
        </span>
      ) : (
        <span
          className="shrink-0 rounded border border-border px-1.5 py-px font-mono text-2xs leading-none text-faint"
          aria-hidden="true"
        >
          /
        </span>
      )}
    </div>
  );
}
