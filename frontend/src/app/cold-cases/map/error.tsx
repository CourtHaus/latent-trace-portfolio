"use client";

import Link from "next/link";

export default function MapErrorBoundary({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  console.error("ColdCaseMapPage error:", error);

  return (
    <div className="flex flex-1 items-center justify-center px-8 py-24">
      <div role="alert" className="flex max-w-md flex-col items-center gap-4 text-center">
        <p className="font-mono text-xs uppercase tracking-eyebrow text-muted-foreground">
          Error
        </p>
        <h1 className="text-2xl font-semibold text-foreground">
          Something went wrong
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          We had trouble loading the map. Our upstream data service may be
          temporarily unavailable.
        </p>
        <div className="mt-2 flex gap-3">
          <button
            type="button"
            onClick={reset}
            className="rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:border-foreground/40"
          >
            Try again
          </button>
          <Link
            href="/cold-cases"
            className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:border-foreground/30"
          >
            Browse all cold cases →
          </Link>
        </div>
      </div>
    </div>
  );
}
