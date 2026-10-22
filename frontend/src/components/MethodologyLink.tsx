import Link from "next/link";
import type { ReactNode } from "react";

export interface MethodologyLinkProps {
  section: "modus-operandi" | "data-sources" | "correlation";
  children: ReactNode;
  className?: string;
}

/**
 * Single source of truth for /methodology anchor links used inline as
 * underlined text. Consumers today: the filter-sidebar MO section header
 * and the detail-page MOSection header. The landing-page TransparencyCloser
 * uses raw button-styled <Link> elements with a different visual treatment,
 * so it doesn't go through this component. Centralizing the href here
 * makes future link rewrites (e.g., methodology-page restructure) a
 * one-line change for the inline-text consumers.
 */
export function MethodologyLink({ section, children, className }: MethodologyLinkProps) {
  return (
    <Link
      href={`/methodology#${section}`}
      className={className ?? "text-sm text-muted-foreground underline hover:text-foreground"}
    >
      {children}
    </Link>
  );
}
