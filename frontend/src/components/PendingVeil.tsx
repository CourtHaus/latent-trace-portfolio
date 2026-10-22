import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Small "Updating…" pill announced politely to assistive tech. Rendered only
 * while a transition is in flight, so screen readers hear the status change.
 */
export function UpdatingBadge() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none absolute inset-x-0 top-3 z-[400] flex justify-center"
    >
      <span className="rounded-full border bg-background/90 px-3 py-1 text-xs font-medium text-muted-foreground shadow-sm backdrop-blur-sm">
        Updating…
      </span>
    </div>
  );
}

export interface PendingVeilProps {
  /** True while a server round-trip (filter/sort/page change) is in flight. */
  isPending: boolean;
  children: ReactNode;
  /**
   * Dim and block interaction on the wrapped content while pending. Default
   * true — appropriate for list/table content where stale rows should read as
   * "being replaced". Set false for surfaces where dimming reads poorly (e.g.
   * a map, where the user may still want to pan during the refetch); the
   * "Updating…" badge alone signals progress there.
   */
  dim?: boolean;
  className?: string;
}

/**
 * Wraps content that is re-fetched in place (not cold-loaded) and gives it a
 * refined pending affordance: a subtle dim plus an "Updating…" badge. We
 * deliberately do NOT swap real content for shimmer skeletons here — the
 * content already exists, and a dim avoids layout shift while keeping context.
 */
export function PendingVeil({ isPending, children, dim = true, className }: PendingVeilProps) {
  return (
    <div
      aria-busy={isPending}
      className={cn(
        "relative transition-opacity",
        dim && isPending && "opacity-60 pointer-events-none",
        className,
      )}
    >
      {children}
      {isPending && <UpdatingBadge />}
    </div>
  );
}
