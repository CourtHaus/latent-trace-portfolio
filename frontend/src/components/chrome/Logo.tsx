import Link from "next/link";

export interface LogoProps {
  size?: "sm" | "md" | "lg";
}

/**
 * Brand mark: Latent Trace fingerprint glyph (concentric arches, brand kit
 * latent_logo.svg) + Pinnacle wordmark. Shared between SiteNav and SiteFooter.
 * The glyph inherits `text-primary` (single-sourced brand orange via
 * currentColor); the wordmark renders in the brand display face (font-headline).
 * Text content stays mixed-case for screen readers / SEO; CSS uppercases it.
 */
export function Logo({ size = "md" }: LogoProps) {
  const textSize =
    size === "sm" ? "text-xs" : size === "lg" ? "text-base" : "text-sm";
  const markSize =
    size === "sm"
      ? "h-[15px] w-[15px]"
      : size === "lg"
        ? "h-[22px] w-[22px]"
        : "h-[18px] w-[18px]";

  return (
    <Link
      href="/"
      className={`flex items-center gap-2.5 font-headline font-semibold uppercase tracking-wider text-foreground hover:text-foreground/90 ${textSize}`}
    >
      <svg
        viewBox="0 0 100 100"
        className={`logo-mark inline-block shrink-0 text-primary ${markSize}`}
        fill="currentColor"
        aria-hidden="true"
        focusable="false"
      >
        <path d="m50 8.332c-11.051 0-21.648 4.3906-29.461 12.207-7.8164 7.8125-12.207 18.41-12.207 29.461v25h8.3359v-25c0-11.91 6.3516-22.914 16.664-28.867 10.316-5.9531 23.02-5.9531 33.336 0 10.312 5.9531 16.664 16.957 16.664 28.867v25h8.332l0.003907-25c0-11.051-4.3906-21.648-12.207-29.461-7.8125-7.8164-18.41-12.207-29.461-12.207z" />
        <path d="m50 20.832c-7.7344 0-15.152 3.0742-20.625 8.543-5.4688 5.4727-8.543 12.891-8.543 20.625v33.332h8.332l0.003907-33.332c0-7.4414 3.9688-14.32 10.414-18.043 6.4453-3.7227 14.391-3.7227 20.836 0 6.4453 3.7227 10.414 10.602 10.414 18.043v33.332h8.332l0.003907-33.332c0-7.7344-3.0742-15.152-8.543-20.625-5.4727-5.4688-12.891-8.543-20.625-8.543z" />
        <path d="m50 33.332c-4.4219 0-8.6602 1.7578-11.785 4.8828s-4.8828 7.3633-4.8828 11.785v41.668h8.332l0.003907-41.668c0-4.6016 3.7305-8.332 8.332-8.332s8.332 3.7305 8.332 8.332v41.668h8.332l0.003907-41.668c0-4.4219-1.7578-8.6602-4.8828-11.785s-7.3633-4.8828-11.785-4.8828z" />
        <path d="m45.832 50h8.332v41.668h-8.332z" />
      </svg>
      <span>Latent Trace</span>
    </Link>
  );
}
