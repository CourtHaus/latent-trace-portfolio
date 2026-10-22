import { parseAsString, parseAsInteger } from "nuqs";
import { filterUrlParsers } from "./filterUrlState";

/**
 * nuqs parsers for /cold-cases/map URL state.
 * Combines the shared filter parsers (filterUrlParsers) with the map-specific
 * bbox + zoom parsers. Consumers can import from here without caring which
 * parsers are shared and which are surface-specific.
 *
 * bbox is treated as an opaque "w,s,e,n" string here. Callers that need the
 * tuple form parse it locally; the URL shape stays forward-compatible with
 * future CRS changes and doesn't couple the parser to leaflet.
 *
 * zoom is the Leaflet zoom level. The server uses it to decide whether to
 * return aggregated clusters (low zoom) or individual case points (high
 * zoom), so it must travel in the URL alongside bbox.
 */
export const mapUrlParsers = {
  ...filterUrlParsers,
  bbox: parseAsString,
  zoom: parseAsInteger,
} as const;
