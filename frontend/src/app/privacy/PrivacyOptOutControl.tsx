"use client";

import { useSyncExternalStore } from "react";
import { optOut } from "@/lib/analytics/client";

const OPT_OUT_KEY = "cs_analytics_optout";
const listeners = new Set<() => void>();

function readOptOutSnapshot(): boolean | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(OPT_OUT_KEY) === "true";
  } catch {
    return false;
  }
}

function subscribeToOptOut(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function notifyOptOutChanged(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function PrivacyOptOutControl() {
  const optedOut = useSyncExternalStore(
    subscribeToOptOut,
    readOptOutSnapshot,
    () => null,
  );

  if (optedOut === null) return null; // SSR placeholder

  if (optedOut) {
    return (
      <p className="rounded border border-border bg-muted px-4 py-3 text-sm">
        You are opted out. No analytics events will be sent from this browser.
      </p>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        optOut();
        notifyOptOutChanged();
      }}
      className="rounded border border-border bg-background px-4 py-2 text-sm hover:bg-muted"
    >
      Opt out of analytics
    </button>
  );
}
