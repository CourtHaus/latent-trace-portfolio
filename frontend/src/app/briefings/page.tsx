import type { Metadata } from "next";
import Link from "next/link";
import { PageLoad } from "@/components/chrome/PageLoad";

export const metadata: Metadata = {
  title: "Briefings",
  description:
    "Briefings is an upcoming question-answering layer over the Latent Trace "
    + "corpus. It is in development and not yet available.",
  alternates: { canonical: "/briefings" },
  openGraph: {
    title: "Briefings · Latent Trace",
    description: "An upcoming question-answering layer over the Latent Trace corpus.",
    url: "/briefings",
  },
};

const SECTION = "px-8 sm:px-12 py-14 border-t border-border";
const COLUMN = "mx-auto max-w-reading";
const EYEBROW =
  "font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground mb-5";
const BODY = "max-w-prose text-base leading-relaxed text-muted-foreground";
const STATUS =
  "inline-block rounded-full border border-border px-3 py-1 font-mono "
  + "text-2xs uppercase tracking-eyebrow text-muted-foreground";

export default function BriefingsPage() {
  return (
    <main>
      <PageLoad>
        {/* ─────────────── OPENING ─────────────── */}
        <section className="px-8 pt-20 pb-10 sm:px-12 sm:pt-30">
          <div className={COLUMN}>
            <div className={EYEBROW}>Briefings</div>
            <h1 className="mb-6 text-4xl font-medium leading-none tracking-tight text-foreground sm:text-5xl">
              Ask the corpus.
            </h1>
            <p className="mb-7">
              <span className={STATUS}>In development</span>
            </p>
            <p className="max-w-prose text-lg leading-relaxed text-muted-foreground">
              {"Briefings will let you put a question to the entire cold-case corpus in plain language and get back a structured answer, with every claim traced to the agency record it came from. It isn't live yet. This page is a placeholder for what's coming."}
            </p>
          </div>
        </section>

        {/* ─────────────── WHAT IT WILL DO ─────────────── */}
        <section className={SECTION}>
          <div className={COLUMN}>
            <h2 className={EYEBROW}>What it will do</h2>
            <div className="space-y-5">
              <p className={BODY}>
                {"Today, asking a cross-cutting question of the data means filtering, sorting, and reading case by case. Briefings will let you ask it directly: describe a pattern, a place, a window of years, or a victim profile, and get a synthesized briefing that pulls the matching cases together and cites each one back to its source."}
              </p>
              <p className={BODY}>{"For example:"}</p>
              <ul className="max-w-prose space-y-2 text-base leading-relaxed text-muted-foreground">
                <li>{"• Unsolved homicides of women along the I-95 corridor between 1985 and 2000."}</li>
                <li>{"• Cases within fifty miles of a location that share a weapon and a victim profile."}</li>
                <li>{"• What is known, and what is missing, across every case tied to a given county."}</li>
              </ul>
              <p className={BODY}>
                {"Every briefing will be a starting point for a person to examine, never an accusation and never a name attached to a crime. The tool points; people decide. Answers will be grounded in what the investigating agency itself reported, with citations you can open and check."}
              </p>
            </div>
          </div>
        </section>

        {/* ─────────────── HOW IT WILL WORK ─────────────── */}
        <section className={SECTION}>
          <div className={COLUMN}>
            <h2 className={EYEBROW}>How it will work</h2>
            <p className={BODY}>
              {"Like the rest of Latent Trace, Briefings will run on local hardware. No case data is handed to an outside company, and the models are held to the same limits described on the "}
              <Link href="/methodology" className="text-accent hover:underline">
                Methodology
              </Link>
              {" page. The "}
              <em className="text-foreground/90">how</em>
              {" will be documented there in full when the feature ships."}
            </p>
          </div>
        </section>

        {/* ─────────────── MEANWHILE ─────────────── */}
        <section className={`${SECTION} pb-24`}>
          <div className={COLUMN}>
            <h2 className={EYEBROW}>In the meantime</h2>
            <p className={BODY}>
              {"The full corpus is already browsable and searchable. Explore it through "}
              <Link href="/cold-cases" className="text-accent hover:underline">
                Cases
              </Link>
              {" and the "}
              <Link href="/cold-cases/map" className="text-accent hover:underline">
                Map
              </Link>
              {", or read how the data is built on the "}
              <Link href="/methodology" className="text-accent hover:underline">
                Methodology
              </Link>
              {" page."}
            </p>
          </div>
        </section>
      </PageLoad>
    </main>
  );
}
