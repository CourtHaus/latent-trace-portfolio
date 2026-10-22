import type { components } from "@/lib/api-types";

export type SortOrder = components["schemas"]["SortOrder"];

export const DEFAULT_SORT: SortOrder = "incident_date_desc";

/**
 * All supported sort orders, in display order. Single source of truth for the
 * toolbar SortSelect options and the register's "sorted by" label. Covers the
 * FULL SortOrder enum so any incoming `?sort=` URL value has a matching option
 * (a controlled <select> with a value outside its options renders blank) and so
 * every server-supported sort is reachable from the UI after the column-header
 * sorting was removed.
 */
export const SORT_OPTIONS: ReadonlyArray<{ value: SortOrder; label: string }> = [
  { value: "incident_date_desc", label: "recency" },
  { value: "incident_date_asc", label: "oldest first" },
  { value: "victim_name_asc", label: "victim name (A–Z)" },
  { value: "victim_name_desc", label: "victim name (Z–A)" },
  { value: "case_type_asc", label: "type (A–Z)" },
  { value: "case_type_desc", label: "type (Z–A)" },
  { value: "location_asc", label: "location (A–Z)" },
  { value: "location_desc", label: "location (Z–A)" },
  { value: "state_asc", label: "state (A–Z)" },
  { value: "state_desc", label: "state (Z–A)" },
  { value: "source_case_id_asc", label: "case ID (asc)" },
  { value: "source_case_id_desc", label: "case ID (desc)" },
];

/** Value → label map derived from SORT_OPTIONS (for the "sorted by" header text). */
export const SORT_LABELS: Readonly<Record<SortOrder, string>> = Object.fromEntries(
  SORT_OPTIONS.map((o) => [o.value, o.label]),
) as Record<SortOrder, string>;
