"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Span {
  start: number;
  end: number;
}

export interface SourceRevealApi {
  transient: Span | null;
  persistent: Span[];
  revealConfident: (span: Span) => void;
  clearAll: () => void;
}

const TRANSIENT_DURATION_MS = 3000;

/**
 * Coordinates source-reveal state on the detail page MO section.
 *
 * - revealConfident(span) starts a transient highlight (~3s) AND adds
 *   the span to a persistent underline list. Persistent underlines
 *   accumulate so users can compare two highlighted spans within the
 *   same narrative.
 * - clearAll() drops both transient and all persistent highlights —
 *   wired to outside-click and Esc on the consumer side.
 *
 * The transient timer is cancelled and replaced when revealConfident is
 * called again (e.g., user clicks Source on the other field). Cleanup
 * on unmount prevents stranded timers.
 */
export function useSourceReveal(): SourceRevealApi {
  const [transient, setTransient] = useState<Span | null>(null);
  const [persistent, setPersistent] = useState<Span[]>([]);
  const transientTimer = useRef<number | null>(null);

  const revealConfident = useCallback((span: Span) => {
    setTransient(span);
    setPersistent((prev) => {
      if (prev.some((p) => p.start === span.start && p.end === span.end)) {
        return prev;
      }
      return [...prev, span];
    });
    if (transientTimer.current !== null) {
      window.clearTimeout(transientTimer.current);
    }
    transientTimer.current = window.setTimeout(() => {
      setTransient(null);
      transientTimer.current = null;
    }, TRANSIENT_DURATION_MS);
  }, []);

  const clearAll = useCallback(() => {
    if (transientTimer.current !== null) {
      window.clearTimeout(transientTimer.current);
      transientTimer.current = null;
    }
    setTransient(null);
    setPersistent([]);
  }, []);

  useEffect(() => {
    return () => {
      if (transientTimer.current !== null) {
        window.clearTimeout(transientTimer.current);
      }
    };
  }, []);

  return { transient, persistent, revealConfident, clearAll };
}
