import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms",
  description:
    "Terms of use for Latent Trace: data accuracy, acceptable use, corrections and removals, and liability.",
  alternates: { canonical: "/terms" },
  openGraph: {
    title: "Terms · Latent Trace",
    description: "Terms of use for Latent Trace: accuracy, acceptable use, corrections, liability.",
    url: "/terms",
  },
};

export default function TermsPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12 space-y-6 text-foreground">
      <h1 className="text-3xl font-semibold tracking-tight">Terms of Use</h1>

      <p className="text-base leading-relaxed text-foreground">
        Latent Trace is a public research tool that aggregates cold-case homicide
        records from official law-enforcement and public-records sources into one
        searchable, mapped, source-cited view. By using this site you agree to
        the terms below. They exist mostly to keep the data from being misused in
        ways that could harm the families and people it concerns, and to be clear
        about what the data is and is not.
      </p>

      <p className="text-base leading-relaxed text-muted-foreground">
        This page is written in plain language and is not legal advice. We are a
        small, self-funded project; if anything here is unclear, email us (see
        Contact) and we will explain it.
      </p>

      <h2 className="text-xl font-semibold mt-8">What Latent Trace is</h2>
      <p className="text-base leading-relaxed text-foreground">
        We collect records that are already public, normalize them into a common
        shape, geocode them, and link each field back to its source. We do not
        originate case facts, and we do not investigate cases ourselves. Every
        case page points to the official source it came from. Some details are
        extracted from source narratives by software running on our own
        hardware; those extracted fields are an overlay on the record, never a
        replacement for it, and they are marked as such.
      </p>

      <h2 className="text-xl font-semibold mt-8">Accuracy and no warranty</h2>
      <p className="text-base leading-relaxed text-foreground">
        The data is drawn from third-party public records and may be incomplete,
        out of date, or wrong. We make no warranty that any record is accurate or
        current. The site is provided &ldquo;as is&rdquo; and &ldquo;as available,&rdquo; without
        warranties of any kind. <strong className="font-medium text-foreground">Latent Trace is not an official record,
        and it must not be used as one</strong>. For authoritative information about a
        case, contact the originating law-enforcement agency.
      </p>

      <h2 className="text-xl font-semibold mt-8">Leads for review, not conclusions</h2>
      <p className="text-base leading-relaxed text-foreground">
        Features that surface possible connections between cases (for example,
        the &ldquo;cases with shared characteristics&rdquo; panel) are statistical leads for human
        review. They are not findings, accusations, or evidence that any case is
        actually connected, and they say nothing about who was involved in any
        crime. Treat them as a starting point for further research through proper
        channels, never as a conclusion about any person.
      </p>

      <h2 className="text-xl font-semibold mt-8">Acceptable use</h2>
      <p className="text-base leading-relaxed text-foreground">
        You may read, search, and reference this data for research, journalism,
        education, and similar good-faith purposes. You may not:
      </p>
      <ul className="space-y-2 text-base leading-relaxed text-muted-foreground list-disc list-inside">
        <li>
          Use Latent Trace to harass, threaten, stalk, surveil, or contact victims,
          their families, witnesses, or any named person.
        </li>
        <li>
          Identify, accuse, or take action against anyone as a suspect. A
          correlation or proximity in this data is not evidence of involvement.
        </li>
        <li>
          Use the data to make decisions about a person&apos;s eligibility for
          employment, housing, credit, insurance, or any similar purpose.
          Latent Trace is not a consumer reporting agency and this is not a
          consumer report.
        </li>
        <li>
          Bulk-scrape, harvest, or systematically download the data, or attempt
          to re-identify or de-anonymize any individual.
        </li>
        <li>
          Republish the data as your own dataset without attribution to
          Latent Trace and the underlying official sources.
        </li>
        <li>Use the site for any unlawful purpose.</li>
      </ul>

      <h2 className="text-xl font-semibold mt-8">Corrections and removals</h2>
      <p className="text-base leading-relaxed text-foreground">
        We take requests from victims&apos; families, named individuals, and agencies
        seriously. If you believe information on this site is inaccurate, out of
        date, or should be removed, email{" "}
        <a href="mailto:courtney@latenttrace.org" className="text-accent hover:underline">courtney@latenttrace.org</a>{" "}
        with the case page URL and a short description of the issue.
      </p>
      <ul className="space-y-2 text-base leading-relaxed text-muted-foreground list-disc list-inside">
        <li>
          Because our records mirror official sources, corrections to the
          underlying facts are usually best made at the source as well, and we
          will update our copy to match once the source is corrected. We will
          also review and fix errors we introduced in aggregating or extracting.
        </li>
        <li>
          We honor good-faith removal requests from a victim&apos;s family or the
          named individual, and lawful requests from agencies, weighed against
          the public-records nature of the data. We would rather err toward the
          family&apos;s wishes.
        </li>
        <li>
          We only publish what the official source provides. We do not add
          inferences the source did not make (for example, a victim&apos;s race is
          never inferred by our software).
        </li>
        <li>We aim to acknowledge requests within a few business days.</li>
      </ul>

      <h2 className="text-xl font-semibold mt-8">Limitation of liability</h2>
      <p className="text-base leading-relaxed text-foreground">
        To the fullest extent allowed by law, Latent Trace and its maintainer are
        not liable for any damages arising from your use of, reliance on, or
        inability to use the site or its data, including damages from inaccurate
        records or from anyone&apos;s misuse of the data. Your use of the site is at
        your own risk.
      </p>

      <h2 className="text-xl font-semibold mt-8">Intellectual property</h2>
      <p className="text-base leading-relaxed text-foreground">
        The underlying case records are public records belonging to their
        originating sources. The site&apos;s design, code, and the particular
        compilation and presentation of the data are Latent Trace&apos;s. If you
        reference the data, please attribute both Latent Trace and the official
        source named on the case page.
      </p>

      <h2 className="text-xl font-semibold mt-8">Changes to these terms</h2>
      <p className="text-base leading-relaxed text-foreground">
        We may update these terms as the project changes. Material changes will
        be reflected in the &ldquo;Last updated&rdquo; date below. Continued use after a
        change means you accept the revised terms.
      </p>

      <h2 className="text-xl font-semibold mt-8">Contact</h2>
      <p className="text-base leading-relaxed text-foreground">
        For corrections, removals, or any question about these terms, email{" "}
        <a href="mailto:courtney@latenttrace.org" className="text-accent hover:underline">courtney@latenttrace.org</a>.
        For how the site handles visitor data, see the{" "}
        <a href="/privacy" className="text-accent hover:underline">Privacy</a> page.
      </p>

      <p className="text-sm text-muted-foreground">Last updated: 2026-06-04</p>
    </main>
  );
}
