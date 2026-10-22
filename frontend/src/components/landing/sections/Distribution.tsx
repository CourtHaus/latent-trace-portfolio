import type { RidgeRow } from "@/lib/decadeHistogram";
import { VizFrame } from "@/components/landing/primitives";
import { Ridgeline } from "@/components/landing/viz/Ridgeline";
import { Heatmap } from "@/components/landing/viz/Heatmap";
import { DECADE_LABELS } from "@/lib/coverageMatrix";
import { ZigZagSection } from "@/components/landing/ZigZagSection";

interface Props {
  ridgeRows: RidgeRow[];
  coverageRows: string[];
  coverageValues: number[][];
}

/**
 * Section 04: the shape of the backlog. Combines temporal incidence density
 * (ridgeline) and jurisdiction x decade coverage (heatmap) side by side — two
 * smaller framed plots in one section. Server component; all data via props.
 * Each plot renders only when its data is present (resilient fallback).
 */
export function Distribution({ ridgeRows, coverageRows, coverageValues }: Props) {
  const dated = ridgeRows.reduce((s, r) => s + r.count, 0);
  const peak = ridgeRows.find((r) => r.peak);
  const ridgeMeta = `n = ${dated.toLocaleString()}${
    peak ? ` · peak ${peak.count.toLocaleString()} (${peak.label})` : ""
  }`;
  const hasRidge = ridgeRows.length > 0;
  const hasCoverage = coverageRows.length > 0;

  return (
    <ZigZagSection
      index="04"
      id="d4"
      title="The shape of the backlog"
      desc="When the unsolved cases happened, and which jurisdictions hold the records. The backlog is uneven in both time and place."
      link={{ href: "/methodology", label: "Methodology" }}
      align="left"
      banded={true}
    >
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {hasRidge && (
          <VizFrame title="Incidence density · KDE by decade" meta={ridgeMeta}>
            <div className="px-4 pb-4 pt-2">
              <Ridgeline rows={ridgeRows} />
            </div>
          </VizFrame>
        )}
        {hasCoverage && (
          <VizFrame
            title="Jurisdiction x decade · record density"
            meta={`${coverageRows.length} states`}
          >
            <div className="p-5">
              <Heatmap rows={coverageRows} cols={DECADE_LABELS} values={coverageValues} />
            </div>
          </VizFrame>
        )}
      </div>
    </ZigZagSection>
  );
}
