import type { SourceSummaryItem } from "@/lib/getSourcesSummary";
import {
  COMPLETENESS_FIELDS,
  SOURCE_METADATA,
  type CompletenessField,
  type CompletenessKind,
} from "@/lib/methodology/sourceMetadata";

interface Props {
  sources: ReadonlyArray<SourceSummaryItem>;
}

const FIELD_LABEL: Record<CompletenessField, string> = {
  case_name: "Name",
  incident_date: "Date",
  address: "Addr.",
  city: "City",
  state: "State",
  gender: "Gender",
  race: "Race",
  age: "Age",
  weapon: "Weapon",
  location_type: "Loc.",
  narrative: "Narr.",
  photograph: "Photo",
};

const KIND_MARK: Record<CompletenessKind, { mark: string; tone: string; label: string }> = {
  structural: { mark: "●", tone: "text-foreground", label: "Source-provided" },
  extracted: { mark: "◐", tone: "text-accent", label: "LLM-extracted" },
  "county-level": { mark: "◑", tone: "text-accent/70", label: "County-level only" },
  missing: { mark: "×", tone: "text-destructive/70", label: "Not in source" },
  none: { mark: "—", tone: "text-muted-foreground/50", label: "Not collected" },
};

export function CompletenessMatrix({ sources }: Props) {
  return (
    <div className="rounded-md border border-border bg-card overflow-x-auto">
      <table className="w-full text-sm min-w-prose">
        <thead>
          <tr className="bg-muted/40 border-b border-border">
            <th className="px-4 py-3 text-left font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground sticky left-0 bg-muted/40 z-10">
              Source
            </th>
            {COMPLETENESS_FIELDS.map((f) => (
              <th
                key={f}
                className="px-2 py-3 text-center font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground whitespace-nowrap"
              >
                {FIELD_LABEL[f]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sources.map((s, idx) => {
            const meta = SOURCE_METADATA[s.code];
            return (
              <tr
                key={s.code}
                className={idx < sources.length - 1 ? "border-b border-border/60" : ""}
              >
                <th
                  scope="row"
                  className="px-4 py-2.5 text-left font-medium text-foreground sticky left-0 bg-card z-10 whitespace-nowrap"
                >
                  <span className="font-mono text-2xs text-muted-foreground mr-2">
                    {s.state ?? "—"}
                  </span>
                  {meta?.shortLabel ?? s.code}
                </th>
                {COMPLETENESS_FIELDS.map((f) => {
                  const kind = meta?.completeness[f];
                  const cell = kind ? KIND_MARK[kind] : KIND_MARK.none;
                  return (
                    <td
                      key={f}
                      className={`px-2 py-2.5 text-center font-mono ${cell.tone}`}
                      title={`${FIELD_LABEL[f]}: ${cell.label}`}
                    >
                      {cell.mark}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function CompletenessLegend() {
  return (
    <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs leading-snug text-muted-foreground">
      {(["structural", "extracted", "county-level", "missing", "none"] as const).map(
        (k) => (
          <span key={k} className="inline-flex items-baseline gap-1.5">
            <span className={`font-mono ${KIND_MARK[k].tone}`}>{KIND_MARK[k].mark}</span>
            <span>{KIND_MARK[k].label}</span>
          </span>
        ),
      )}
    </div>
  );
}
