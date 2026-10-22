import { OutlineButton } from "@/components/landing/primitives";

const PRINCIPLES = [
  {
    n: "01",
    title: "Source-traceable",
    desc: "Every extracted field links to the verbatim source span it came from.",
  },
  {
    n: "02",
    title: "Local extraction",
    desc: "All inference runs on local hardware. Vendor APIs are never used.",
  },
  {
    n: "03",
    title: "No ad tech",
    desc: "No ads or analytics cookies. A few product events via PostHog, with one-click opt-out.",
  },
  {
    n: "04",
    title: "Open access",
    desc: "Free to use. No login wall in front of the public record.",
  },
] as const;

/** Section 01: Methodology band. Server component, no props. */
export function MethodologyBand() {
  return (
    <section
      className="border-t border-hair bg-card py-24"
      aria-labelledby="d1"
    >
      <div className="wrap-wide grid items-center gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        {/* Left: copy + CTA */}
        <div>
          <span className="font-mono text-xs tracking-widest text-accent">
            01 / Methodology
          </span>
          <h2
            id="d1"
            className="mt-3.5 font-display text-[clamp(28px,3.6vw,48px)] font-bold leading-none tracking-tight"
          >
            Source-led research.{" "}
            <em className="not-italic text-accent">Traceable</em> by default.
          </h2>
          <p className="mt-4.5 max-w-[46ch] text-base leading-relaxed text-muted-foreground">
            <strong className="font-medium text-foreground">
              Every figure traces back to a public record.
            </strong>{" "}
            Narrative extraction uses a locally hosted model. Source links,
            extraction provenance, and geographic precision help you assess
            each result. The methodology and privacy pages explain the process
            and external services.
          </p>
          <div className="mt-6">
            <OutlineButton href="/methodology" primary>
              Read the methodology
            </OutlineButton>
          </div>
        </div>

        {/* Right: 2x2 principles grid */}
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[14px] border border-hair bg-hair">
          {PRINCIPLES.map((p) => (
            <div key={p.n} className="bg-card p-6">
              <div className="font-mono text-2xs uppercase tracking-eyebrow text-accent">
                {p.n}
              </div>
              <h3 className="mt-2.5 font-display text-lg font-semibold">
                {p.title}
              </h3>
              <p className="mt-1.5 text-xs leading-normal text-muted-foreground">
                {p.desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
