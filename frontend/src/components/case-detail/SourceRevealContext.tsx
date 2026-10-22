"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useSourceReveal, type SourceRevealApi } from "./SourceRevealController";

export interface SourceRevealCtx extends SourceRevealApi {
  /** Whether #case-narrative exists on the page (drives aria-controls). */
  hasNarrative: boolean;
}

const Ctx = createContext<SourceRevealCtx | null>(null);

/**
 * Shares one source-reveal state across sibling blocks (MO panel, victim
 * cards) so any of them can highlight a span in the case narrative.
 * Components must tolerate a null context (rendered outside the detail
 * page / in isolation in tests) and degrade to a non-interactive display.
 */
export function SourceRevealProvider({
  hasNarrative,
  children,
}: {
  hasNarrative: boolean;
  children: ReactNode;
}) {
  const api = useSourceReveal();
  // Memoize on the hook's individual fields (the hook returns a fresh object
  // literal each render) so consumers only re-render on actual state
  // transitions, not on every provider render.
  const value = useMemo(
    () => ({ ...api, hasNarrative }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [api.transient, api.persistent, api.revealConfident, api.clearAll, hasNarrative]
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSourceRevealCtx(): SourceRevealCtx | null {
  return useContext(Ctx);
}
