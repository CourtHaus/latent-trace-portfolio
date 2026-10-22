/**
 * Pure render component for a single-case map marker. Rendered via
 * renderToStaticMarkup inside L.divIcon from MapLeaflet. Sidesteps
 * Leaflet's default-icon PNG assets not being served by Next's bundler.
 *
 * Per-precision variants differentiate within the Glacier palette family
 * (opacity + outline) rather than introducing new hues.
 */

export type GeocodePrecision = "street" | "landmark" | "zip" | "county";

interface Props {
  precision?: GeocodePrecision;
}

const PRECISION_CLASS: Record<GeocodePrecision, string> = {
  // Descending visual "completeness": full fill → outlined-only.
  street: "marker--street bg-primary ring-2 ring-background",
  landmark: "marker--landmark bg-primary/80 ring-2 ring-background",
  zip: "marker--zip bg-primary/50 ring-2 ring-background",
  county: "marker--county bg-transparent ring-2 ring-primary",
};

export function MarkerDivIcon({ precision }: Props) {
  const cls = precision
    ? PRECISION_CLASS[precision]
    : "bg-primary ring-2 ring-background";
  return (
    <div
      aria-hidden="true"
      style={{ width: 14, height: 14 }}
      className={`rounded-full shadow-md ${cls}`}
    />
  );
}
