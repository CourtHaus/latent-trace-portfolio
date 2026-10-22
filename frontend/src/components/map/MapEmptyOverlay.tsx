import { Button } from "@/components/ui/button";

export interface MapEmptyOverlayProps {
  /** Clears narrow-down filters (viewport is preserved by the caller). */
  onReset: () => void;
  /** Flies back to the default national view — a one-click escape from an
   *  empty zoomed-in area. */
  onRecenter: () => void;
}

/**
 * Informational card shown over the map when the current filters + viewport
 * leave zero cases to plot. The entire overlay — backdrop AND card — is
 * click/scroll-through (pointer-events-none); only the action buttons capture
 * events. That way the user can still scroll-zoom and drag the map *through*
 * the card to get back to cases, instead of the card trapping the wheel.
 */
export function MapEmptyOverlay({ onReset, onRecenter }: MapEmptyOverlayProps) {
  return (
    <div className="pointer-events-none absolute inset-0 z-[400] flex items-center justify-center p-4">
      <div className="max-w-sm rounded-lg border bg-background/95 p-6 text-center shadow-md backdrop-blur-sm">
        <h2 className="mb-1 text-base font-semibold">No cases in this view</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          No cases match these filters in the current map area. Scroll to zoom
          out, recenter to the national view, or broaden your filters.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="pointer-events-auto"
            onClick={onRecenter}
          >
            Recenter
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="pointer-events-auto"
            onClick={onReset}
          >
            Reset filters
          </Button>
        </div>
      </div>
    </div>
  );
}
