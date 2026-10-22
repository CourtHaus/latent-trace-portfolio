"use client";

import { useEffect, useState } from "react";
import { GeoJSON } from "react-leaflet";
import { feature } from "topojson-client";
import type { Feature, FeatureCollection, Geometry } from "geojson";

interface Props {
  fips: string | null;
}

// Module-level cache so the ~1MB atlas only loads once per browser session.
let atlasPromise: Promise<FeatureCollection> | null = null;

async function loadCounties(): Promise<FeatureCollection> {
  if (atlasPromise) return atlasPromise;
  atlasPromise = (async () => {
    const mod = await import("us-atlas/counties-10m.json");
    const topojson = (mod as any).default ?? mod; // eslint-disable-line @typescript-eslint/no-explicit-any
    const fc = feature(topojson, topojson.objects.counties) as unknown as FeatureCollection;
    return fc;
  })();
  return atlasPromise;
}

export function CountyOverlay({ fips }: Props) {
  // Track {fips, geom} as a pair so render can require they match. This
  // sidesteps the cascading-setState-in-effect ESLint rule (no setState
  // on the no-op null branch) and also closes a flash bug where a stale
  // geometry from a previous fips would briefly render against the new
  // fips during the async load.
  const [loaded, setLoaded] = useState<{ fips: string; geom: Feature<Geometry> } | null>(null);

  useEffect(() => {
    if (!fips) return;
    let cancelled = false;
    loadCounties()
      .then((fc) => {
        if (cancelled) return;
        const target = String(fips).padStart(5, "0");
        const match = fc.features.find(
          (f) =>
            String((f as Feature & { id?: string | number }).id ?? "").padStart(5, "0") === target,
        );
        if (match) setLoaded({ fips, geom: match as Feature<Geometry> });
      })
      .catch(() => {
        // Swallow — overlay is a decorative layer; no geometry just means no render.
      });
    return () => {
      cancelled = true;
    };
  }, [fips]);

  if (!fips) return null;
  if (!loaded || loaded.fips !== fips) return null;

  return (
    // react-leaflet injects the polygon into Leaflet's own overlay pane, so this
    // wrapper renders nothing visible — it's just the React mount point (and a
    // test hook). Kept hidden rather than removed; GeoJSON needs a parent here.
    <div data-testid="county-overlay" style={{ display: "none" }}>
      <GeoJSON
        data={loaded.geom}
        style={{
          fillColor: "var(--color-primary)",
          fillOpacity: 0.15,
          color: "var(--color-primary)",
          weight: 2,
        }}
      />
    </div>
  );
}
