import Link from "next/link";

export default function MapNotFound() {
  return (
    <div className="flex flex-1 items-center justify-center px-8 py-24">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <p className="font-mono text-xs uppercase tracking-eyebrow text-muted-foreground">
          404
        </p>
        <h1 className="text-2xl font-semibold text-foreground">
          Map unavailable
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          We couldn&apos;t load the map right now. Try again in a moment or
          browse cases as a list.
        </p>
        <Link
          href="/cold-cases"
          className="mt-2 rounded-md border border-border px-4 py-2 text-sm text-foreground hover:border-foreground/30"
        >
          Browse all cold cases →
        </Link>
      </div>
    </div>
  );
}
