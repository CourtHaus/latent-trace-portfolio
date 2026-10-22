"use client";

import L from "leaflet";
import { renderToStaticMarkup } from "react-dom/server";
import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  ZoomControl,
  AttributionControl,
  useMap,
  useMapEvent,
} from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import type { components } from "@/lib/api-types";
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM } from "@/lib/mapDefaults";
import { cartoTileUrl, TILE_ATTRIBUTION } from "@/lib/mapTiles";
import { track } from "@/lib/analytics/client";
import { createDebouncedTracker } from "@/lib/analytics/createDebouncedTracker";
import { MarkerPopup } from "./MarkerPopup";
import { ClusterIcon, clusterTierSize } from "./ClusterIcon";
import { MarkerDivIcon, type GeocodePrecision } from "./MarkerDivIcon";
import { CountyOverlay } from "./CountyOverlay";
import { useCountyOverlayState } from "./useCountyOverlayState";

type ColdCaseMapItem = components["schemas"]["ColdCaseMapItem"];
type ColdCaseMapClusterItem = components["schemas"]["ColdCaseMapClusterItem"];
type MapMode = components["schemas"]["ColdCaseMapResponse"]["mode"];

// Module-level icon cache. There are exactly 5 possible inputs (the 4
// precision tiers + "no precision"), so we render the SVG-ish HTML once
// and reuse the L.DivIcon instance across all markers. Without this,
// every render of MapLeaflet calls renderToStaticMarkup N times where
// N = visible markers; with thousands of markers and frequent state
// updates (e.g. county-overlay clicks), that synchronous work pegs the
// main thread and starves both Leaflet's render loop and any in-flight
// API requests.
const ICON_CACHE: Record<string, L.DivIcon> = {};

function getMarkerIcon(precision: string | null | undefined): L.DivIcon {
  const key = precision ?? "default";
  if (!ICON_CACHE[key]) {
    ICON_CACHE[key] = L.divIcon({
      html: renderToStaticMarkup(
        <MarkerDivIcon precision={(precision ?? undefined) as GeocodePrecision | undefined} />
      ),
      className: "",
      iconSize: L.point(14, 14),
      iconAnchor: L.point(7, 7),
    });
  }
  return ICON_CACHE[key];
}

// Server-cluster bubble icons keyed by count — the ClusterIcon markup only
// depends on the count, so cache by count to avoid re-rendering markup for
// repeat values across cells.
const CLUSTER_ICON_CACHE: Record<number, L.DivIcon> = {};

function getClusterIcon(count: number): L.DivIcon {
  if (!CLUSTER_ICON_CACHE[count]) {
    const size = clusterTierSize(count);
    CLUSTER_ICON_CACHE[count] = L.divIcon({
      html: renderToStaticMarkup(<ClusterIcon count={count} />),
      className: "",
      iconSize: L.point(size, size),
    });
  }
  return CLUSTER_ICON_CACHE[count];
}

export interface MapLeafletProps {
  mode: MapMode;
  data: ColdCaseMapItem[];
  clusters: ColdCaseMapClusterItem[];
  initialBbox: [number, number, number, number] | null;
  initialZoom: number;
  shouldFitBounds: boolean;
  /** Commit the post-move viewport: (bbox "w,s,e,n", leaflet zoom). */
  onViewportChange: (bbox: string, zoom: number) => void;
  onRecenterToken: number;
}

function MapEventBridge({
  fitPoints,
  shouldFitBounds,
  onViewportChange,
  onRecenterToken,
  onMapClick,
}: {
  fitPoints: Array<[number, number]>;
  shouldFitBounds: boolean;
  onViewportChange: (bbox: string, zoom: number) => void;
  onRecenterToken: number;
  onMapClick: () => void;
}) {
  const map = useMap();

  // Initial fit only if no URL bbox. Fits to whatever is loaded — points or
  // cluster centroids.
  useEffect(() => {
    if (!shouldFitBounds) return;
    if (fitPoints.length === 0) return;
    map.fitBounds(L.latLngBounds(fitPoints), { padding: [20, 20] });
    // Run once on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Recenter: triggered by parent changing the token
  useEffect(() => {
    if (onRecenterToken === 0) return; // skip initial mount
    map.flyTo(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onRecenterToken]);

  // Debounced tracker for viewport-change telemetry
  const viewportTracker = useMemo(
    () =>
      createDebouncedTracker(
        () => track("map_interacted", { interaction_type: "viewport_changed" }),
        1000,
      ),
    [],
  );

  useEffect(() => () => viewportTracker.cancel(), [viewportTracker]);

  // moveend → commit bbox + zoom to URL. Clamp to valid lon/lat ranges: when
  // zoomed out the viewport can be wider than the world, so getBounds() returns
  // longitudes past ±180 (and lats past ±90), which the API rejects with 422.
  useMapEvent("moveend", () => {
    const b = map.getBounds();
    const clampLng = (v: number) => Math.max(-180, Math.min(180, v));
    const clampLat = (v: number) => Math.max(-90, Math.min(90, v));
    const bbox = [
      clampLng(b.getWest()).toFixed(4),
      clampLat(b.getSouth()).toFixed(4),
      clampLng(b.getEast()).toFixed(4),
      clampLat(b.getNorth()).toFixed(4),
    ].join(",");
    onViewportChange(bbox, map.getZoom());
    viewportTracker();
  });

  // map background click → dismiss county overlay
  useMapEvent("click", () => onMapClick());

  return null;
}

// Single CaseMarker, memoized so that re-renders of the parent MapLeaflet
// (e.g. when activeFips changes after a county-overlay click) do NOT
// recreate every Marker. Click handler is read off a ref so it stays
// referentially stable across renders without invalidating the memo.
interface CaseMarkerProps {
  c: ColdCaseMapItem;
  onClickRef: React.MutableRefObject<(c: ColdCaseMapItem) => void>;
}

const CaseMarker = memo(function CaseMarker({ c, onClickRef }: CaseMarkerProps) {
  const handlers = useMemo(
    () => ({
      click: () => {
        track("map_interacted", { interaction_type: "marker_clicked", case_id: c.case_id });
        onClickRef.current(c);
      },
    }),
    // onClickRef is a stable ref; c is the marker's data
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [c.case_id, c.latitude, c.longitude, c.geocode_precision]
  );
  return (
    <Marker
      position={[c.latitude, c.longitude]}
      icon={getMarkerIcon(c.geocode_precision)}
      eventHandlers={handlers}
    >
      {/* autoPan disabled: with marker-cluster, a data refetch can move/replace
          a marker that has an open popup, and Leaflet's _adjustPan then derefs a
          (transiently) null map. Skipping autoPan avoids that crash path. */}
      <Popup autoPan={false}>
        <MarkerPopup case={c} />
      </Popup>
    </Marker>
  );
});

// Server-aggregated cluster bubble. Clicking zooms in toward the cell so the
// next refetch returns finer clusters — and, past the cluster threshold,
// individual case points.
const ClusterBubble = memo(function ClusterBubble({
  cluster,
}: {
  cluster: ColdCaseMapClusterItem;
}) {
  const map = useMap();
  const handlers = useMemo(
    () => ({
      click: () => {
        track("map_interacted", { interaction_type: "viewport_changed" });
        const target = Math.min(map.getZoom() + 3, 14);
        map.flyTo([cluster.latitude, cluster.longitude], target);
      },
    }),
    // map is stable; cluster identity is its coordinates + count
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cluster.latitude, cluster.longitude, cluster.count],
  );
  return (
    <Marker
      position={[cluster.latitude, cluster.longitude]}
      icon={getClusterIcon(cluster.count)}
      eventHandlers={handlers}
    />
  );
});

export function MapLeaflet({
  mode,
  data,
  clusters,
  initialBbox,
  initialZoom,
  shouldFitBounds,
  onViewportChange,
  onRecenterToken,
}: MapLeafletProps) {
  // App is dark-only (force-dark; light mode deferred). Always use the dark
  // CARTO basemap — keying off resolvedTheme rendered the light (white) tiles
  // whenever the theme wasn't resolved yet. Re-introduce the conditional when
  // a light theme ships.
  const tileUrl = cartoTileUrl("dark");
  const { activeFips, onPinClick, onMapClick } = useCountyOverlayState();

  // Mirror the click callbacks into refs so CaseMarker can call the
  // freshest version without taking the function itself as a dep.
  const onPinClickRef = useRef(onPinClick);
  useEffect(() => {
    onPinClickRef.current = onPinClick;
  });
  const onMapClickRef = useRef(onMapClick);
  useEffect(() => {
    onMapClickRef.current = onMapClick;
  });
  const stableMapClick = useCallback(() => onMapClickRef.current(), []);

  const clusterIconCreate = useCallback(
    (cluster: { getChildCount: () => number }) => {
      const count = cluster.getChildCount();
      const size = clusterTierSize(count);
      return L.divIcon({
        html: renderToStaticMarkup(<ClusterIcon count={count} />),
        className: "",
        iconSize: L.point(size, size),
      });
    },
    []
  );

  const initialCenter: [number, number] = initialBbox
    ? [(initialBbox[1] + initialBbox[3]) / 2, (initialBbox[0] + initialBbox[2]) / 2]
    : DEFAULT_MAP_CENTER;

  // Coordinates used for the one-time initial fit-to-bounds — whichever
  // representation the server returned.
  const fitPoints: Array<[number, number]> =
    mode === "clusters"
      ? clusters.map((c) => [c.latitude, c.longitude])
      : data.map((c) => [c.latitude, c.longitude]);

  return (
    <MapContainer
      center={initialCenter}
      zoom={initialZoom}
      zoomControl={false}
      attributionControl={false}
      className="flex-1 h-full"
    >
      <AttributionControl position="bottomleft" />
      <ZoomControl position="bottomleft" />
      <TileLayer
        attribution={TILE_ATTRIBUTION}
        url={tileUrl}
      />
      <MapEventBridge
        fitPoints={fitPoints}
        shouldFitBounds={shouldFitBounds}
        onViewportChange={onViewportChange}
        onRecenterToken={onRecenterToken}
        onMapClick={stableMapClick}
      />
      {mode === "clusters" ? (
        // Server already aggregated — render bubbles directly, no
        // client-side MarkerClusterGroup (that would re-cluster clusters).
        clusters.map((c) => (
          <ClusterBubble key={`${c.latitude},${c.longitude}`} cluster={c} />
        ))
      ) : (
        <MarkerClusterGroup iconCreateFunction={clusterIconCreate}>
          {data.map((c) => (
            <CaseMarker key={c.case_id} c={c} onClickRef={onPinClickRef} />
          ))}
        </MarkerClusterGroup>
      )}
      <CountyOverlay fips={activeFips} />
    </MapContainer>
  );
}
