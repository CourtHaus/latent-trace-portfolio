import type { RidgeRow } from "@/lib/decadeHistogram";
import { HeroRidge } from "@/components/landing/viz/HeroRidge";
import { Reveal } from "@/components/landing/Reveal";
import { OutlineButton, StatRail } from "@/components/landing/primitives";

interface Props {
  total: number;
  geocodedPct: number;
  spanYears: number;
  jurisdictions: number;
  ridgeRows: RidgeRow[];
}

export function Hero({ total, geocodedPct, spanYears, jurisdictions, ridgeRows }: Props) {
  return (
    <header className="relative flex min-h-[calc(100dvh-86px)] flex-col overflow-hidden">
      {/* Ambient ridge decoration */}
      <div className="absolute bottom-24 right-[-4%] z-[1] w-[62%] opacity-55 pointer-events-none">
        <HeroRidge rows={ridgeRows} />
      </div>

      {/* Vertical edge label */}
      <span
        aria-hidden="true"
        className="absolute left-[18px] top-[46%] z-[3] hidden -translate-y-1/2 rotate-180 font-mono text-2xs uppercase tracking-eyebrow text-faint [writing-mode:vertical-rl] sm:block"
      >
        Latent Trace · Cold-case intelligence system
      </span>

      {/* Top-right HUD readout */}
      <div
        aria-hidden="true"
        className="absolute right-[clamp(26px,3vw,56px)] top-[26px] z-[3] hidden text-right font-mono text-2xs uppercase leading-loose tracking-eyebrow text-faint sm:block"
      >
        LAT 39.1031 N<br />
        LON 084.5120 W<br />
        GRID · CONUS<br />
        REC {total.toLocaleString()} · OPEN
      </div>

      {/* Corner ticks */}
      <span
        aria-hidden="true"
        className="absolute left-[30px] top-[18px] z-[3] h-[15px] w-[15px] border border-r-0 border-b-0 border-border"
      />
      <span
        aria-hidden="true"
        className="absolute bottom-24 right-[30px] z-[3] h-[15px] w-[15px] border border-l-0 border-t-0 border-border"
      />

      {/* Hero content: left-anchored via .edge padding */}
      <div className="edge relative z-[2] flex flex-1 items-center">
        <div className="max-w-[58ch]">
          <Reveal delay={0}>
            <div className="flex items-center gap-3 font-mono text-2xs uppercase tracking-eyebrow text-accent before:block before:h-px before:w-[34px] before:bg-accent before:content-['']">
              Cold-case intelligence
            </div>
          </Reveal>

          <Reveal delay={80}>
            <h1
              className="mt-5 max-w-[14ch] font-display font-extrabold leading-none tracking-tight [font-size:clamp(46px,7vw,98px)] [text-wrap:balance]"
            >
              A century of unsolved cases, made{" "}
              <em className="not-italic text-accent">legible</em>.
            </h1>
          </Reveal>

          <Reveal delay={160}>
            <p className="mt-5.5 max-w-[52ch] text-lg leading-relaxed text-muted-foreground">
              <b className="font-medium text-foreground">
                {total.toLocaleString()} cold-case homicides across {jurisdictions} jurisdictions
              </b>
              , normalized, geocoded, and correlated into one operational record. Built for the
              analysts working the cases no one is assigned to.
            </p>
          </Reveal>

          <Reveal delay={240}>
            <div className="mt-7.5 flex gap-3.5">
              <OutlineButton href="/cold-cases" primary>Open the index</OutlineButton>
              <OutlineButton href="/cold-cases/map">View the map</OutlineButton>
            </div>
          </Reveal>
        </div>
      </div>

      {/* Stat rail */}
      <Reveal delay={320}>
        <div className="edge relative z-[4] border-t border-border bg-gradient-to-b from-transparent to-background/60">
          <StatRail
            items={[
              { to: total, label: "Unsolved records" },
              { to: jurisdictions, label: "Jurisdictions" },
              { to: geocodedPct, suffix: "%", label: "Geocoded" },
              { to: spanYears, suffix: "y", label: "Coverage span" },
            ]}
          />
        </div>
      </Reveal>
    </header>
  );
}
