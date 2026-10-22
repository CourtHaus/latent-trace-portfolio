import {
  parseAsArrayOf,
  parseAsInteger,
  parseAsString,
  parseAsStringEnum,
} from "nuqs";

/**
 * nuqs parsers for filters shared by /cold-cases and /cold-cases/map.
 * Filter keys match the backend endpoint's query params verbatim.
 * Array filters serialize to comma-separated values in the URL.
 */
export const filterUrlParsers = {
  year_min: parseAsInteger,
  year_max: parseAsInteger,
  case_type: parseAsArrayOf(parseAsString),
  city: parseAsString,
  gender: parseAsArrayOf(parseAsString),
  race: parseAsArrayOf(parseAsString),
  weapon: parseAsArrayOf(parseAsString),
  location_type: parseAsArrayOf(parseAsString),
  source_system: parseAsArrayOf(parseAsString),
  precision: parseAsArrayOf(parseAsString),
  q: parseAsString,
  sort: parseAsStringEnum([
    "incident_date_desc",
    "incident_date_asc",
    "victim_name_asc",
    "victim_name_desc",
    "source_case_id_asc",
    "source_case_id_desc",
    "case_type_asc",
    "case_type_desc",
    "location_asc",
    "location_desc",
    "state_asc",
    "state_desc",
  ]).withDefault("incident_date_desc"),
} as const;
