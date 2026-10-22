import type { Metadata } from "next";
import Link from "next/link";
import { PageLoad } from "@/components/chrome/PageLoad";

export const metadata: Metadata = {
  title: "About",
  description:
    "Why Latent Trace exists and who stands behind it: an independent, "
    + "self-funded effort to unify cold homicide records from official sources.",
  alternates: { canonical: "/about" },
  openGraph: {
    title: "About · Latent Trace",
    description: "Why Latent Trace exists and who stands behind it.",
    url: "/about",
  },
};

const SECTION = "px-8 sm:px-12 py-14 border-t border-border";
const COLUMN = "mx-auto max-w-reading";
const EYEBROW =
  "font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground mb-5";
const BODY = "max-w-prose text-base leading-relaxed text-muted-foreground";

export default function AboutPage() {
  return (
    <main>
      <PageLoad>
        {/* ─────────────── OPENING ─────────────── */}
        <section className="px-8 pt-20 pb-10 sm:px-12 sm:pt-30">
          <div className={COLUMN}>
            <div className={EYEBROW}>About</div>
            <h1 className="mb-6 text-4xl font-medium leading-none tracking-tight text-foreground sm:text-5xl">
              Why this exists.
            </h1>
            <p className="max-w-prose text-lg leading-relaxed text-muted-foreground">
              {"A homicide case doesn't close because it goes cold. The questions stay open, the grief stays unprocessed, and the person at the center of it is still owed an answer. What changes is everyone else's attention. Memory fades, evidence degrades, investigators get pulled to the next emergency. Time is the one advantage a cold case hands to whoever got away with it."}
            </p>
            <p className="mt-5 max-w-prose text-lg leading-relaxed text-foreground">
              {"Latent Trace exists to take some of that advantage back."}
            </p>
          </div>
        </section>

        {/* ─────────────── WHY COLD CASES ─────────────── */}
        <section className={SECTION}>
          <div className={COLUMN}>
            <h2 className={EYEBROW}>Why cold cases</h2>
            <div className="space-y-5">
              <p className={BODY}>
                {"More cold cases are being solved by the public now than ever before. People with patience, databases, and a reason to care have identified victims and named offenders that institutions alone could not. But that only works when the underlying facts are sound. The longer a case sits, the more a single misreported detail (a wrong date, a transposed digit, a guess repeated until it hardens into fact) gets treated as settled truth. Misinformation doesn't just mislead; it convinces someone holding a genuinely useful piece of information that it couldn't possibly matter. That's why Latent Trace only ever shows what the investigating agency itself reported. No news clippings, no aggregators, no secondhand retellings. The primary record, or nothing."}
              </p>
              <p className={BODY}>
                {"And some of these cases were never going to be solved one jurisdiction at a time. We know there are offenders who crossed state lines and left behind victims we still can't name. Today, a researcher, a journalist, or a family member who suspects a connection has almost no way to ask the obvious question: "}
                <em className="text-foreground/90">
                  {"this person was in this place, in these years; are there unsolved cases here that fit?"}
                </em>
                {" Answering it means manually trawling dozens of incompatible agency websites, when the data is online at all. Latent Trace is built to make that question answerable. Every connection it surfaces is a lead for a person to examine, never an accusation, never a name attached to a crime. The tool points; people decide."}
              </p>
              <p className={BODY}>
                {"These victims matter, and they don't stop mattering when the people who loved them are gone. As families age and pass on, a case can lose the one person who kept it in the conversation, who made sure it was still being worked, still remembered, still owed justice. Part of what this corpus does is simply refuse to let them disappear."}
              </p>
            </div>
          </div>
        </section>

        {/* ─────────────── WHY I BUILT IT ─────────────── */}
        <section className={SECTION}>
          <div className={COLUMN}>
            <h2 className={EYEBROW}>Why I built it</h2>
            <div className="space-y-5">
              <p className={BODY}>
                {"I'm Courtney Hammond. Latent Trace exists because the resource it provides did not, and because the need was too important to leave unmet. For years I had watched cold-case data sit scattered, inconsistently structured, and incomplete, in a way that quietly fails victims, their families, and the agencies that rely on the public's help. What I lacked, until recently, were the technical skills to address it; those came with completing my bachelor's in computer science and beginning my master's. I can't think of a more worthwhile place to put them."}
              </p>
              <p className={BODY}>
                {"NamUs, which focuses on the unidentified, does essential work, but homicide victims who are named deserve the same standard of access and care, and they have not received it. The records that do exist are spread in scattered, incomplete fragments across individual agency sites. I won't pretend to know exactly why; the reasons are likely some combination of limited funding, lost case files, and institutional caution. Virginia has shown that it can be done well, yet almost no other state has followed. True-crime media helps keep these cases visible, and that matters, but it runs into the same walls anyone does: thin public records, older reporting of uncertain accuracy, and no way to see across cases, because until now no multi-state corpus existed. So I'm building one."}
              </p>
              <p className={BODY}>
                {"The project is independent and self-funded: no advertising, no investors, nothing for sale. Narrative extraction uses a locally hosted model, and the models are never permitted to infer a victim's race. Hosting, geocoding, and optional source tooling use separate services described in the privacy policy. The "}
                <em className="text-foreground/90">how</em>
                {" of all of that lives on the "}
                <Link href="/methodology" className="text-accent hover:underline">
                  Methodology
                </Link>
                {" page."}
              </p>
            </div>
          </div>
        </section>

        {/* ─────────────── WHAT WOULD MAKE IT WORTH IT ─────────────── */}
        <section className={SECTION}>
          <div className={COLUMN}>
            <h2 className={EYEBROW}>What would make it worth it</h2>
            <p className={BODY}>
              {"I'm not measuring this in page views. Success is any way the needle moves. If Latent Trace nudges agencies toward sharing cold-case information in a consolidated, usable way, that's a win. If it comes to hold a pin for every victim still waiting on justice, that's a win. And if it encourages even a few people with data-science or AI skills to aim them at civic good instead of the next ad-tech problem, I'll count that one too."}
            </p>
          </div>
        </section>

        {/* ─────────────── CONTACT ─────────────── */}
        <section className={`${SECTION} pb-24`}>
          <div className={COLUMN}>
            <h2 className={EYEBROW}>Contact</h2>
            <p className={BODY}>
              {"If you're a family member, an investigator, or an agency, and something here is wrong, or something here is painful and shouldn't be public the way it is, please tell me. Latent Trace corrects to the agency record, and I'd rather hear it from you. "}
              <a
                href="mailto:courtney@latenttrace.org"
                className="font-medium text-foreground hover:text-accent"
              >
                courtney@latenttrace.org
              </a>
            </p>
          </div>
        </section>
      </PageLoad>
    </main>
  );
}
