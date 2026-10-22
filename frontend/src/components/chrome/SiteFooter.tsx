import Link from "next/link";
import { getFilterOptionsOrNull } from "@/lib/getFilterOptions";
import { Logo } from "./Logo";

export async function SiteFooter() {
  const options = await getFilterOptionsOrNull();
  const year = new Date().getFullYear();
  const sources = options?.source_systems ?? [];
  const datasetVersion = options?.dataset.version ?? "n/a";

  return (
    <footer className="border-t border-border bg-card">
      <div className="bleed py-10">
        <div className="flex flex-col gap-10 border-b border-border pb-6 md:flex-row md:justify-between">
          <div className="max-w-md">
            <Logo />
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Open-access analytics for unsolved cold cases.
              Non-commercial. Public-domain record aggregation.
            </p>
          </div>
          <div>
            <div className="mb-3 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
              Data sources
            </div>
            <p className="max-w-xs text-sm leading-relaxed text-muted-foreground">
              {`Aggregated from ${sources.length} official law-enforcement source${sources.length === 1 ? "" : "s"}. `}
              <Link href="/methodology#data-sources" className="text-accent hover:underline">
                See coverage
              </Link>
            </p>
          </div>
        </div>
        <div className="flex flex-col items-start justify-between gap-3 pt-5 md:flex-row md:items-center">
          <div className="flex gap-5 text-sm text-muted-foreground">
            <Link href="/methodology" className="hover:text-foreground">Methodology</Link>
            <Link href="/privacy" className="hover:text-foreground">Privacy</Link>
            <Link href="/terms" className="hover:text-foreground">Terms</Link>
            <a href="mailto:courtney@latenttrace.org" className="hover:text-foreground">Contact</a>
          </div>
          <div className="font-mono text-2xs text-muted-foreground/80">
            DATASET {datasetVersion} · © {year} Latent Trace
          </div>
        </div>
      </div>
    </footer>
  );
}
