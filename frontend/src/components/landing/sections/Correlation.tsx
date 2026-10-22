import { VizFrame } from "@/components/landing/primitives";
import { JointScatter, RankedLeads } from "@/components/landing/viz/JointPlot";
import type { JointPlotProps } from "@/components/landing/viz/JointPlot";
import { ZigZagSection } from "@/components/landing/ZigZagSection";

/** Section 04: Correlation across jurisdiction lines. Server component. Real featured-case data via props. */
export function Correlation({ points, leads }: JointPlotProps) {
  return (
    <ZigZagSection
      index="03"
      id="d3"
      title="Correlation across jurisdiction lines"
      desc="Every pair scored on proximity, time, and modus operandi. The strongest correlations surface for analyst review."
      align="right"
      banded={false}
    >
      <div className="grid gap-4.5 lg:grid-cols-[1.05fr_.95fr]">
        {/* Scatter */}
        <VizFrame
          title="Joint distribution · distance x time"
          meta={`${points.length} candidates`}
        >
          <div className="p-4">
            <JointScatter points={points} />
          </div>
          {/* Legend */}
          <div className="flex items-center gap-6 border-t border-hair px-5 py-3">
            <LegendDot color="var(--accent)" label="Strong correlation" />
            <LegendDot color="rgb(92,101,112)" label="Candidate" />
            <LegendDot color="rgb(44,49,57)" label="Below threshold" />
          </div>
        </VizFrame>

        {/* Ranked leads */}
        <VizFrame
          title="Top correlations"
          meta={`${leads.length} above threshold`}
        >
          <RankedLeads leads={leads} />
        </VizFrame>
      </div>
    </ZigZagSection>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-2 font-mono text-2xs text-faint">
      <span
        style={{ background: color }}
        className="inline-block h-[7px] w-[7px] rounded-full"
      />
      {label}
    </span>
  );
}
