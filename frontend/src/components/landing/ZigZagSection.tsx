import Link from "next/link";

export function ZigZagSection({
  index, id, title, desc, link, align = "left", banded = false, children,
}: {
  index: string; id: string; title: string; desc?: string;
  link?: { href: string; label: string };
  align?: "left" | "right"; banded?: boolean; children: React.ReactNode;
}) {
  const right = align === "right";
  return (
    <section className={`border-t border-hair py-24 ${banded ? "bg-card" : ""}`}>
      <div className="wrap-wide">
        <header className={`max-w-[640px] ${right ? "ml-auto" : ""} ${right ? "text-right" : "text-left"}`}>
          <div className="font-mono text-xs tracking-widest text-accent">{index}</div>
          <h2 id={id} className="mt-3.5 font-display text-3xl font-bold tracking-tight text-foreground sm:text-4xl">{title}</h2>
          {desc && <p className={`mt-3 max-w-[48ch] text-sm leading-relaxed text-muted-foreground ${right ? "ml-auto" : ""}`}>{desc}</p>}
          {link && (
            <Link href={link.href}
              className="mt-4 inline-block whitespace-nowrap border-b border-border pb-1 font-mono text-2xs uppercase tracking-snug text-foreground transition-colors hover:border-accent hover:text-white">
              {link.label}
            </Link>
          )}
        </header>
        <div className="mt-12">{children}</div>
      </div>
    </section>
  );
}
