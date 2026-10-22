import Link from "next/link";

export default function CaseNotFound() {
  return (
    <div className="flex flex-1 items-center justify-center px-8 py-24">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <p className="font-mono text-xs uppercase tracking-eyebrow text-muted-foreground">
          404
        </p>
        <h1 className="text-2xl font-semibold text-foreground">
          Case not found
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          We don&apos;t have a record for this case. It may have been removed
          from the dataset, or the URL might be wrong.
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
