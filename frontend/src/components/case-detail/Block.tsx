import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface BlockProps {
  /** Header title — rendered as an <h2> so the block is a labelled landmark. */
  title: ReactNode;
  /** Stable id for the heading; the <section> is aria-labelledby it. */
  headingId: string;
  /** Right-aligned accent tag in the header bar (e.g. "GEOCODED", "TIER-1"). */
  tag?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Override body padding/layout (e.g. p-0 for a flush map). */
  bodyClassName?: string;
}

/**
 * Framed "block": a rounded-2xl card with a card→inset gradient, inset +
 * drop shadow, and a hairline header bar (mono uppercase title + optional
 * accent tag) over a padded body — the VizFrame treatment with retained
 * landmark semantics. The header is the section's accessible name, so wrapped
 * components should NOT render their own duplicate heading.
 */
export function Block({
  title,
  headingId,
  tag,
  children,
  className,
  bodyClassName,
}: BlockProps) {
  return (
    <section
      aria-labelledby={headingId}
      className={cn(
        "overflow-hidden rounded-2xl border border-border bg-gradient-to-b from-card to-inset shadow-[inset_0_1px_0_rgba(255,255,255,.04),0_18px_44px_rgba(0,0,0,.4)]",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-hair px-4 py-3">
        <h2
          id={headingId}
          className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground"
        >
          {title}
        </h2>
        {tag != null && (
          <span className="font-mono text-2xs uppercase tracking-eyebrow text-accent">
            {tag}
          </span>
        )}
      </div>
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
