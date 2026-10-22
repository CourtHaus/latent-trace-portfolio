import { Children, cloneElement, isValidElement, type ReactNode } from "react";

export interface PageLoadProps {
  children: ReactNode;
  /** Per-child stagger delay in ms (default 80). */
  stagger?: number;
}

/**
 * Applies a one-time staggered fade-in to immediate React children on first mount.
 * CSS-only via globals.css .page-load-child class. Respects prefers-reduced-motion.
 *
 * Non-element children (strings, null) pass through unchanged.
 */
export function PageLoad({ children, stagger = 80 }: PageLoadProps) {
  let idx = 0;
  return (
    <>
      {Children.map(children, (child) => {
        if (!isValidElement(child)) return child;
        const el = child as React.ReactElement<{
          className?: string;
          style?: React.CSSProperties;
        }>;
        const delay = idx++ * stagger;
        const existingClass = el.props.className ?? "";
        return cloneElement(el, {
          className: `${existingClass} page-load-child`.trim(),
          style: { ...el.props.style, animationDelay: `${delay}ms` },
        });
      })}
    </>
  );
}
