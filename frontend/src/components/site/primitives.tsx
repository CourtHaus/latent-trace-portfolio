import Link from "next/link";
import { CountUp } from "@/components/landing/Reveal";

export function SectionHeader({ idx, id, title, desc, link }: {
  idx: string; id: string; title: string; desc?: string;
  link?: { href: string; label: string };
}) {
  return (
    <div className="mb-8 flex items-baseline justify-between gap-6">
      <div className="flex items-baseline gap-4.5">
        <span className="font-mono text-xs tracking-widest text-accent">{idx}</span>
        <div>
          <h2 id={id} className="font-display text-3xl font-bold tracking-tight sm:text-4xl">{title}</h2>
          {desc && <p className="mt-2 max-w-[46ch] text-sm text-muted-foreground">{desc}</p>}
        </div>
      </div>
      {link && (
        <Link href={link.href}
          className="whitespace-nowrap border-b border-border pb-1 font-mono text-2xs uppercase tracking-snug text-foreground transition-colors hover:border-accent hover:text-white">
          {link.label}
        </Link>
      )}
    </div>
  );
}

export function VizFrame({ title, meta, children, className = "" }: {
  title: string; meta?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={`overflow-hidden rounded-2xl border border-border bg-gradient-to-b from-card to-inset shadow-[inset_0_1px_0_rgba(255,255,255,.04),0_30px_80px_rgba(0,0,0,.5)] ${className}`}>
      <div className="flex items-center justify-between border-b border-hair px-4.5 py-4">
        <span className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">{title}</span>
        {meta && <span className="font-mono text-2xs text-faint">{meta}</span>}
      </div>
      {children}
    </div>
  );
}

export function OutlineButton({ href, children, primary = false }: {
  href: string; children: React.ReactNode; primary?: boolean;
}) {
  return (
    <Link href={href}
      className={`inline-flex items-center rounded-lg border px-5.5 py-3 font-display text-sm font-semibold uppercase tracking-wider text-foreground transition hover:-translate-y-px hover:bg-white/[.035]
        ${primary ? "border-white/25 hover:border-muted-foreground" : "border-border hover:border-muted-foreground"}`}>
      {children}
    </Link>
  );
}

export interface StatItem {
  /** Counted value (animated). Provide this OR `display`. */
  to?: number;
  suffix?: string;
  /** Static text (e.g. "1961–2023"); rendered verbatim, no CountUp. */
  display?: string;
  label: string;
}

export function StatRail({ items }: { items: StatItem[] }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4">
      {items.map((s, i) => (
        <div key={s.label} className={i > 0 ? "border-l border-hair pl-7 pr-6 py-5" : "pr-6 py-5"}>
          <div className="font-display text-4xl font-bold leading-none tracking-tight">
            {s.display != null ? s.display : <CountUp to={s.to ?? 0} suffix={s.suffix} />}
          </div>
          <div className="mt-2 font-mono text-2xs uppercase tracking-eyebrow text-faint">{s.label}</div>
        </div>
      ))}
    </div>
  );
}
