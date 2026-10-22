import Link from "next/link";
import { humanizeCaseType } from "@/lib/humanizeCaseType";
import { formatCaseDate } from "@/lib/formatCaseDate";
import type { components } from "@/lib/api-types";

type ColdCaseMapItem = components["schemas"]["ColdCaseMapItem"];

interface MarkerPopupProps {
  case: ColdCaseMapItem;
}

export function MarkerPopup({ case: c }: MarkerPopupProps) {
  const location = [c.city, c.state].filter(Boolean).join(", ");
  const displayName = c.victim_primary_name ?? "Unidentified";

  return (
    <div className="w-[220px]">
      <div className="flex items-center justify-between gap-3 border-b border-hair bg-elev px-3 py-2">
        <h3 className="text-sm font-semibold text-foreground">{displayName}</h3>
        <span className="shrink-0 font-mono text-2xs text-accent">#{c.source_case_id}</span>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 px-3 py-2.5">
        <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Type</dt>
        <dd className="text-right text-sm text-foreground">{humanizeCaseType(c.case_type)}</dd>
        {c.incident_date && (
          <>
            <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Date</dt>
            <dd className="text-right text-sm tabular-nums text-foreground">
              {formatCaseDate(c.incident_date)}
            </dd>
          </>
        )}
        <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Location</dt>
        <dd className="text-right text-sm text-foreground">{location}</dd>
      </dl>
      <Link
        href={`/cold-cases/${c.case_id}/${c.slug}`}
        className="block border-t border-hair px-3 py-2 font-mono text-2xs text-accent transition-colors hover:bg-elev"
      >
        View case →
      </Link>
    </div>
  );
}
