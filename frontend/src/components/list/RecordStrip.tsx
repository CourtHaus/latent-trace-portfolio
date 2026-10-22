import Link from "next/link";
import { CaseTypeBadge } from "@/components/CaseTypeBadge";
import { humanizeCaseType } from "@/lib/humanizeCaseType";
import { humanizeGender } from "@/lib/humanizeGender";
import type { components } from "@/lib/api-types";

type ColdCaseListItem = components["schemas"]["ColdCaseListItem"];

function caseYear(incidentDate: string | null): string {
  return incidentDate ? incidentDate.slice(0, 4) : "—";
}

/** Mono micro-tag for one demographic; dims to "<label> n/a" when null. */
function DemoTag({ label, value }: { label: string; value: string | null }) {
  const missing = value == null;
  return (
    <span
      className={
        "inline-flex items-center whitespace-nowrap rounded border px-2 py-0.5 font-mono text-2xs uppercase tracking-eyebrow " +
        (missing ? "border-hair text-faint" : "border-border text-muted-foreground")
      }
    >
      {missing ? `${label} n/a` : value}
    </span>
  );
}

/** One cold-case record as a responsive three-zone strip (identity · demographics ·
 *  location). Whole strip links to the case detail. Replaces ListTable + ListCards. */
export function RecordStrip({ row }: { row: ColdCaseListItem }) {
  const name = row.victim_primary_name ?? "Unidentified";
  const isUnidentified = row.victim_primary_name === null;
  const year = caseYear(row.incident_date);
  const geocoded = row.geocode_precision != null && row.geocode_precision !== "failed";
  const age = row.victim_primary_age != null ? `Age ${row.victim_primary_age}` : null;
  const location = [row.city, row.state].filter(Boolean).join(", ");
  const ariaLabel = `${name}, ${humanizeCaseType(row.case_type)}, ${year}, ${location}`;

  return (
    <Link
      href={`/cold-cases/${row.case_id}/${row.slug}`}
      aria-label={ariaLabel}
      className="group grid grid-cols-1 overflow-hidden rounded-lg border border-hair bg-card transition-colors hover:border-accent/40 hover:bg-elev hover:ring-1 hover:ring-accent/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:grid-cols-[minmax(220px,1.5fr)_minmax(240px,1.7fr)_minmax(150px,0.8fr)]"
    >
      {/* Identity */}
      <div className="flex flex-col justify-center px-4 py-2.5 lg:border-r lg:border-hair">
        <span
          className={
            "font-display text-base font-semibold leading-tight transition-colors group-hover:text-accent " +
            (isUnidentified ? "italic text-muted-foreground" : "text-foreground")
          }
        >
          {name}
        </span>
        <span className="mt-0.5 font-mono text-2xs text-faint">
          <span className="text-accent">{year}</span> · {row.source_case_id}
        </span>
      </div>

      {/* Demographics */}
      <div className="flex flex-row flex-wrap items-center gap-1.5 px-4 py-2.5 lg:border-r lg:border-hair">
        <CaseTypeBadge caseType={row.case_type} />
        <DemoTag label="Gender" value={humanizeGender(row.victim_primary_gender)} />
        <DemoTag label="Age" value={age} />
        <DemoTag label="Race" value={row.victim_primary_race} />
      </div>

      {/* Location */}
      <div className="flex flex-col justify-center px-4 py-2.5 lg:items-end lg:text-right">
        <span className="font-display text-lg font-bold leading-none">{row.state}</span>
        {row.city && <span className="mt-0.5 text-xs text-muted-foreground">{row.city}</span>}
        <span className={"mt-1 font-mono text-2xs " + (geocoded ? "text-success" : "text-faint")}>
          {geocoded ? (
            <>
              <span aria-hidden="true">✓ </span>geocoded
            </>
          ) : (
            <>
              <span aria-hidden="true">— </span>no coords
            </>
          )}
        </span>
      </div>
    </Link>
  );
}
