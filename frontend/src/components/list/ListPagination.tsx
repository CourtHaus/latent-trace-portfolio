import Link from "next/link";
import { cn } from "@/lib/utils";
import { buildListUrl } from "@/lib/buildListUrl";

export interface ListPaginationProps {
  currentPage: number;
  totalPages: number;
  totalFiltered: number;
  searchParams: Record<string, string | string[] | undefined>;
}

const BTN =
  "inline-flex h-7 min-w-7 items-center justify-center rounded border border-border bg-card px-2 font-mono text-2xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const ACTIVE = "border-primary text-primary";
const DISABLED = "pointer-events-none opacity-40";

/**
 * Server component — renders discoverable <a href> pagination controls so
 * Googlebot can crawl paginated results. Filter-preservation is delegated
 * to buildListUrl. Styled as the Instrument ".pager": a mono record/page
 * summary on the left, bordered page buttons on the right (current = accent).
 *
 * Uses Next.js <Link> directly (not shadcn's PaginationLink which wraps a
 * Button + role="button") to keep real link semantics for SEO + a11y.
 */
export function ListPagination({
  currentPage,
  totalPages,
  totalFiltered,
  searchParams,
}: ListPaginationProps) {
  if (totalPages <= 1) return null;

  const pageNumbers = buildPageNumberSequence(currentPage, totalPages);
  const hasPrev = currentPage > 1;
  const hasNext = currentPage < totalPages;

  return (
    <nav
      className="mt-3.5 flex items-center justify-between gap-3 font-mono text-2xs text-faint"
      aria-label="Pagination"
    >
      <span className="tabular-nums">
        {totalFiltered.toLocaleString()} records · {totalPages.toLocaleString()} pages
      </span>
      <div className="flex items-center gap-1.5">
        {hasPrev ? (
          <Link
            href={buildListUrl(searchParams, { page: currentPage - 1 })}
            aria-label="Previous page"
            className={BTN}
          >
            ‹
          </Link>
        ) : (
          <span aria-disabled="true" aria-label="Previous page" className={cn(BTN, DISABLED)}>
            ‹
          </span>
        )}

        {pageNumbers.map((n, idx) =>
          n === "ellipsis" ? (
            <span
              key={`ellipsis-${idx}`}
              aria-hidden="true"
              className="px-1 font-mono text-2xs text-faint"
            >
              …
            </span>
          ) : (
            <Link
              key={n}
              href={buildListUrl(searchParams, { page: n })}
              aria-current={n === currentPage ? "page" : undefined}
              className={cn(BTN, n === currentPage && ACTIVE)}
            >
              {n}
            </Link>
          ),
        )}

        {hasNext ? (
          <Link
            href={buildListUrl(searchParams, { page: currentPage + 1 })}
            aria-label="Next page"
            className={BTN}
          >
            ›
          </Link>
        ) : (
          <span aria-disabled="true" aria-label="Next page" className={cn(BTN, DISABLED)}>
            ›
          </span>
        )}
      </div>
    </nav>
  );
}

/**
 * Compact page-number sequence with ellipses.
 * 5-page list → [1,2,3,4,5]
 * 20 pages on current 6 → [1, "ellipsis", 5,6,7, "ellipsis", 20]
 */
function buildPageNumberSequence(
  current: number,
  total: number,
): (number | "ellipsis")[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const result: (number | "ellipsis")[] = [1];
  if (current > 3) result.push("ellipsis");
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) result.push(i);
  if (current < total - 2) result.push("ellipsis");
  result.push(total);
  return result;
}
