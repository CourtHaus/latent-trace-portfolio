"use client";

import { useEffect, useRef } from "react";
import type { Span } from "./SourceRevealController";

export interface NarrativeWithHighlightsProps {
  text: string;
  transient: Span | null;
  persistent: Span[];
  onClearAll: () => void;
}

interface Segment {
  text: string;
  isTransient: boolean;
  isPersistent: boolean;
}

function buildSegments(text: string, transient: Span | null, persistent: Span[]): Segment[] {
  const breakpoints = new Set<number>([0, text.length]);
  for (const p of persistent) {
    breakpoints.add(p.start);
    breakpoints.add(p.end);
  }
  if (transient) {
    breakpoints.add(transient.start);
    breakpoints.add(transient.end);
  }
  const sorted = Array.from(breakpoints).sort((a, b) => a - b);
  const segments: Segment[] = [];
  for (let i = 0; i < sorted.length - 1; i++) {
    const start = sorted[i]!;
    const end = sorted[i + 1]!;
    const slice = text.slice(start, end);
    if (!slice) continue;
    const containsTransient =
      transient !== null && transient.start <= start && transient.end >= end;
    const containsPersistent = persistent.some(
      (p) => p.start <= start && p.end >= end
    );
    segments.push({
      text: slice,
      isTransient: containsTransient,
      isPersistent: containsPersistent,
    });
  }
  return segments;
}

/**
 * Renders the about_text narrative with optional highlight overlays.
 *
 * - The first transient segment receives a smooth-scrollIntoView call
 *   on mount/transient-change; prefers-reduced-motion downgrades the
 *   scroll to "auto" and skips the fade animation.
 * - Live region announces the highlighted text content for screen readers.
 * - Outside-click and Esc clear all highlights via onClearAll.
 */
export function NarrativeWithHighlights({
  text,
  transient,
  persistent,
  onClearAll,
}: NarrativeWithHighlightsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const transientRef = useRef<HTMLElement | null>(null);
  const liveRegionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (transient && transientRef.current) {
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      transientRef.current.scrollIntoView({
        behavior: reduced ? "auto" : "smooth",
        block: "center",
      });
      const phrase = text.slice(transient.start, transient.end);
      if (liveRegionRef.current) {
        liveRegionRef.current.textContent = `Source phrase highlighted: "${phrase}".`;
      }
    }
  }, [transient, text]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClearAll();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClearAll]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) {
        onClearAll();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClearAll]);

  const segments = buildSegments(text, transient, persistent);
  // Only the first transient segment receives the ref + the smooth-transition
  // styling. Computed before the map so we don't mutate a closure variable
  // during render.
  const firstTransientIdx = segments.findIndex((s) => s.isTransient);

  return (
    <>
      <div
        id="case-narrative"
        ref={containerRef}
        className="max-w-none whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground"
      >
        {segments.map((seg, idx) => {
          if (seg.isTransient && idx === firstTransientIdx) {
            return (
              <mark
                key={idx}
                ref={(el) => {
                  transientRef.current = el;
                }}
                className="rounded-[3px] bg-accent-dim px-1 text-accent ring-1 ring-accent/70 transition-shadow duration-700 motion-reduce:transition-none"
              >
                {seg.text}
              </mark>
            );
          }
          if (seg.isTransient) {
            return (
              <mark
                key={idx}
                className="rounded-[3px] bg-accent-dim px-1 text-accent ring-1 ring-accent/70 motion-reduce:transition-none"
              >
                {seg.text}
              </mark>
            );
          }
          if (seg.isPersistent) {
            // Always-on extraction highlight (the default state for every
            // anchored extracted field). Clicking "Source ▸" promotes one span
            // to transient (adds the ring + scrolls it into view).
            return (
              <mark key={idx} className="rounded-[3px] bg-accent-dim px-1 text-accent">
                {seg.text}
              </mark>
            );
          }
          return <span key={idx}>{seg.text}</span>;
        })}
      </div>
      <div
        ref={liveRegionRef}
        role="status"
        aria-live="polite"
        className="sr-only"
      />
    </>
  );
}
