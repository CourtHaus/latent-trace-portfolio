"use client";

import { MapContainer, TileLayer, Marker } from "react-leaflet";
import { useTheme } from "next-themes";
import { renderToStaticMarkup } from "react-dom/server";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MarkerDivIcon, type GeocodePrecision } from "@/components/map/MarkerDivIcon";
import { cartoTileUrl, TILE_ATTRIBUTION } from "@/lib/mapTiles";

const PRECISIONS: ReadonlySet<string> = new Set(["street", "landmark", "zip", "county"]);

function pinIcon(precision: string | null): L.DivIcon {
  const p = precision && PRECISIONS.has(precision) ? (precision as GeocodePrecision) : undefined;
  return L.divIcon({
    html: renderToStaticMarkup(<MarkerDivIcon precision={p} />),
    className: "",
    iconSize: L.point(14, 14),
    iconAnchor: L.point(7, 7),
  });
}

export interface CaseLocationMapInnerProps {
  lat: number;
  lng: number;
  precision: string | null;
}

/** Single-pin mini-map for the detail page's Recovery location block. Static
 *  feel (no scroll-zoom hijack), one marker styled by geocode precision. */
export default function CaseLocationMapInner({ lat, lng, precision }: CaseLocationMapInnerProps) {
  const { resolvedTheme } = useTheme();
  const tileUrl = cartoTileUrl(resolvedTheme === "dark" ? "dark" : "light");
  return (
    <MapContainer
      center={[lat, lng]}
      zoom={11}
      className="h-full w-full bg-inset"
      zoomControl={false}
      attributionControl={true}
      scrollWheelZoom={false}
      doubleClickZoom={false}
    >
      <TileLayer url={tileUrl} attribution={TILE_ATTRIBUTION} />
      <Marker position={[lat, lng]} icon={pinIcon(precision)} />
    </MapContainer>
  );
}
