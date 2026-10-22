/**
 * Streaming fallback for the cold-cases list while its RSC data fetch resolves.
 * A lightweight skeleton (no client JS) so navigation feels instant instead of
 * blocking on the API round-trip.
 */
export default function ColdCasesLoading() {
  return (
    <div className="mx-auto w-[min(1680px,100%-7vw)] pb-12 pt-8" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading cold cases…</span>
      <div className="mb-8 h-8 w-64 animate-pulse rounded bg-muted" />
      <div className="space-y-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="h-12 w-full animate-pulse rounded bg-muted"
          />
        ))}
      </div>
    </div>
  );
}
