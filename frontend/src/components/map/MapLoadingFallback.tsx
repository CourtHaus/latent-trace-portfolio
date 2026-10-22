/**
 * Cold-load placeholder shown while the Leaflet bundle is dynamically
 * imported. Unlike a filter re-fetch (where content already exists and we
 * dim it), here there is genuinely nothing yet — so a labeled placeholder is
 * the honest signal, especially on slow mobile networks where a bare pulsing
 * box reads as broken.
 */
export function MapLoadingFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex-1 flex items-center justify-center bg-muted animate-pulse"
    >
      <span className="text-sm text-muted-foreground">Loading map…</span>
    </div>
  );
}
