import Link from "next/link";

// Root 404. Renders inside the app shell (nav + footer), so a dead link or a
// removed/unpublished case lands on a branded page instead of Next's default.
export default function NotFound() {
  return (
    <div className="flex flex-1 items-center justify-center px-8 py-24">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <p className="font-mono text-xs uppercase tracking-eyebrow text-muted-foreground">
          404
        </p>
        <h1 className="text-2xl font-semibold text-foreground">
          Page not found
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          That page does not exist. A case may also have been removed if its
          source agency unpublished the record. Try the register or the map.
        </p>
        <div className="mt-2 flex gap-3">
          <Link
            href="/cold-cases"
            className="rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:border-foreground/40"
          >
            Browse cases
          </Link>
          <Link
            href="/"
            className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:border-foreground/30"
          >
            Home →
          </Link>
        </div>
      </div>
    </div>
  );
}
