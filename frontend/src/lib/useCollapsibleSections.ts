"use client";

import { useCallback, useSyncExternalStore } from "react";

export interface CollapsibleSectionsApi {
  collapsed: string[];
  isCollapsed: (id: string) => boolean;
  toggle: (id: string) => void;
}

// Same-tab subscriber registry. The browser's `storage` event fires for
// OTHER tabs only, so for cross-instance updates within the same tab we
// maintain our own listener set and notify on writes.
const sameTabListeners = new Set<() => void>();

const EMPTY: string[] = [];

// Snapshot cache. useSyncExternalStore loops if getSnapshot returns a new
// array reference every read, so we cache the parsed array keyed by
// `<key>:<validIdsKey>:<raw>`. Stale entries fall out naturally because
// the raw value is part of the cache key.
const snapshotCache = new Map<string, string[]>();

// In-memory fallback for environments where localStorage WRITES throw (private
// browsing, quota/full storage). Without it, a toggle whose setItem fails leaves
// no persisted state, the re-read sees raw === null, and a default-collapsed
// section snaps back to collapsed — so those users could never open it. Holds
// the last intended state per key; consulted only when localStorage can't.
const memoryStore = new Map<string, string[]>();

function subscribe(callback: () => void): () => void {
  sameTabListeners.add(callback);
  if (typeof window !== "undefined") {
    window.addEventListener("storage", callback);
  }
  return () => {
    sameTabListeners.delete(callback);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", callback);
    }
  };
}

function notifySameTab(): void {
  sameTabListeners.forEach((cb) => cb());
}

// Stable, filtered default-collapsed list per (validIds, defaults) pair. Cached
// so useSyncExternalStore sees a constant reference — returning a fresh array
// each read makes it loop.
const defaultCache = new Map<string, string[]>();

function getDefaultCollapsed(validIdsKey: string, defaultKey: string): string[] {
  if (!defaultKey) return EMPTY;
  const cacheKey = `${validIdsKey}::${defaultKey}`;
  const cached = defaultCache.get(cacheKey);
  if (cached) return cached;
  const validSet = new Set(validIdsKey.split("|").filter(Boolean));
  const filtered = defaultKey.split("|").filter((id) => id && validSet.has(id));
  const value = filtered.length > 0 ? filtered : EMPTY;
  defaultCache.set(cacheKey, value);
  return value;
}

function getSnapshot(
  key: string,
  validIdsKey: string,
  defaultKey: string,
): string[] {
  if (typeof window === "undefined") {
    return getDefaultCollapsed(validIdsKey, defaultKey);
  }
  let raw: string | null;
  try {
    raw = localStorage.getItem(key);
  } catch {
    // localStorage unavailable for reads too → use the in-memory fallback.
    return memoryStore.get(key) ?? getDefaultCollapsed(validIdsKey, defaultKey);
  }
  // A prior write may have failed (storage full / private mode), leaving the
  // intended state only in memory; prefer it over the absent stored value so
  // the toggle still takes effect.
  if (raw === null && memoryStore.has(key)) {
    return memoryStore.get(key)!;
  }
  const cacheKey = `${key}:${validIdsKey}:${defaultKey}:${raw ?? "<null>"}`;
  const cached = snapshotCache.get(cacheKey);
  if (cached) return cached;

  // No stored preference yet → fall back to the caller's default-collapsed set.
  // A stored value (even "[]") is authoritative: once the user has touched any
  // section, their explicit state wins — including "everything expanded".
  let value: string[] = getDefaultCollapsed(validIdsKey, defaultKey);
  if (raw !== null) {
    value = EMPTY;
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const validSet = new Set(validIdsKey.split("|").filter(Boolean));
        const filtered = parsed.filter(
          (id): id is string => typeof id === "string" && validSet.has(id),
        );
        if (filtered.length > 0) value = filtered;
      }
    } catch {
      // Malformed entry — start expanded.
    }
  }
  snapshotCache.set(cacheKey, value);
  return value;
}

function getServerSnapshot(validIdsKey: string, defaultKey: string): string[] {
  return getDefaultCollapsed(validIdsKey, defaultKey);
}

function invalidateCacheForKey(key: string): void {
  for (const cacheKey of snapshotCache.keys()) {
    if (cacheKey.startsWith(`${key}:`)) {
      snapshotCache.delete(cacheKey);
    }
  }
}

/**
 * Per-user UI preference for which sidebar sections are collapsed.
 * Stored in localStorage — never in the URL — because section-collapse
 * doesn't change query results and shouldn't travel with shared links
 * or impose layout preferences on link recipients.
 *
 * Reads via useSyncExternalStore so SSR returns an empty list (no
 * hydration mismatch), the client reads from localStorage on first
 * paint, and cross-tab + same-tab writes propagate consistently.
 *
 * `validIds` filters stale localStorage entries when a section is
 * renamed or removed — keeps state self-correcting across refactors.
 *
 * `defaultCollapsed` seeds which sections start collapsed before the user
 * has expressed any preference (and on the server, so SSR matches and there
 * is no first-paint flash). Once a stored preference exists it takes over.
 */
export function useCollapsibleSections(
  key: string,
  validIds: readonly string[],
  defaultCollapsed: readonly string[] = EMPTY,
): CollapsibleSectionsApi {
  const validIdsKey = validIds.join("|");
  const defaultKey = defaultCollapsed.join("|");

  const collapsed = useSyncExternalStore(
    subscribe,
    () => getSnapshot(key, validIdsKey, defaultKey),
    () => getServerSnapshot(validIdsKey, defaultKey),
  );

  const toggle = useCallback(
    (id: string) => {
      const current = getSnapshot(key, validIdsKey, defaultKey);
      const next = current.includes(id)
        ? current.filter((v) => v !== id)
        : [...current, id];
      try {
        localStorage.setItem(key, JSON.stringify(next));
        // Persisted: localStorage is now authoritative; drop any memory fallback.
        memoryStore.delete(key);
      } catch {
        // Quota exceeded / private mode: keep the intended state in memory so the
        // toggle still takes effect (getSnapshot falls back to it when raw null).
        memoryStore.set(key, next);
      }
      invalidateCacheForKey(key);
      notifySameTab();
    },
    [key, validIdsKey, defaultKey],
  );

  const isCollapsed = useCallback(
    (id: string) => collapsed.includes(id),
    [collapsed],
  );

  return { collapsed, isCollapsed, toggle };
}
