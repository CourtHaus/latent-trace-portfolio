import { feature } from "topojson-client";
import type {
  Feature,
  FeatureCollection,
  Geometry,
  MultiPolygon,
  Polygon,
} from "geojson";
import topology from "us-atlas/states-albers-10m.json";

/** FIPS state code → USPS two-letter abbreviation. Includes DC. */
const FIPS_TO_USPS: Record<string, string> = {
  "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
  "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
  "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
  "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
  "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
  "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
  "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
  "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
  "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
  "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
  "56": "WY",
};

interface StateProps {
  name: string;
}

type StateFeature = Feature<MultiPolygon | Polygon, StateProps>;

interface Props {
  /** USPS state codes that have at least one source ingested. */
  coveredStates: ReadonlyArray<string>;
  /** USPS state codes with partial sub-state coverage (e.g. county-only). */
  partialStates?: ReadonlyArray<string>;
}

function pathFromFeature(f: StateFeature): string {
  const polys: number[][][][] =
    f.geometry.type === "MultiPolygon"
      ? (f.geometry.coordinates as number[][][][])
      : [f.geometry.coordinates as number[][][]];
  return polys
    .flatMap((poly) =>
      poly.map(
        (ring) =>
          "M" +
          ring
            .map((pt) => `${(pt[0] ?? 0).toFixed(1)},${(pt[1] ?? 0).toFixed(1)}`)
            .join("L") +
          "Z",
      ),
    )
    .join(" ");
}

// us-atlas/states-albers-10m fits inside roughly [0, 0, 960, 600].
const VIEWBOX = "0 0 960 600";

export function CoverageMap({ coveredStates, partialStates = [] }: Props) {
  const covered = new Set(coveredStates);
  const partial = new Set(partialStates);

  // Cast: us-atlas JSON imports as `any` from the typings perspective, but the
  // structure is a valid TopoJSON topology with a `states` object collection.
  const collection = feature(
    topology as unknown as Parameters<typeof feature>[0],
    (topology as unknown as { objects: { states: unknown } }).objects.states as Parameters<
      typeof feature
    >[1],
  ) as unknown as FeatureCollection<MultiPolygon | Polygon, StateProps>;

  return (
    <svg
      viewBox={VIEWBOX}
      role="img"
      aria-label="US map showing Latent Trace coverage by state"
      className="w-full h-auto"
    >
      <title>Latent Trace coverage map</title>
      {collection.features.map((f: Feature<Geometry, StateProps>) => {
        const fips =
          typeof f.id === "string" ? f.id : String(f.id ?? "").padStart(2, "0");
        const code = FIPS_TO_USPS[fips];
        const isCovered = code ? covered.has(code) : false;
        const isPartial = code ? partial.has(code) : false;

        // Color tokens map to Tailwind theme variables via fill-current trick.
        // We use the `text-*` color, then fill="currentColor" on the <path>.
        // Partial takes precedence over covered: a state with only county-level
        // coverage (e.g. MD) appears in both sets but should read as partial.
        let toneClass = "text-muted/40";
        if (isPartial) toneClass = "text-accent/30";
        else if (isCovered) toneClass = "text-accent/70";

        return (
          <path
            key={fips}
            d={pathFromFeature(f as StateFeature)}
            fill="currentColor"
            stroke="var(--background)"
            strokeWidth={0.6}
            strokeLinejoin="round"
            className={toneClass}
          >
            <desc>
              {f.properties.name}
              {isCovered ? ": covered" : isPartial ? ": partial coverage" : ""}
            </desc>
          </path>
        );
      })}
    </svg>
  );
}
