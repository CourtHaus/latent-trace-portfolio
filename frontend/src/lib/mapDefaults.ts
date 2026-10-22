/**
 * Default Leaflet view for the cold-case map. Plain constants — no nuqs /
 * client-only imports — so the server map page can import these without
 * pulling client code into the server bundle.
 *
 * Shared so the server page (which must request the right cluster/point
 * mode before the client mounts) and the client MapLeaflet agree on the
 * initial view.
 */
export const DEFAULT_MAP_ZOOM = 7;
export const DEFAULT_MAP_CENTER: [number, number] = [37.7, -79.0];
