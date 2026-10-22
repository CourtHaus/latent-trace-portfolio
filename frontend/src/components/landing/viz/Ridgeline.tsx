import type { RidgeRow } from "@/lib/decadeHistogram";

interface Props {
  rows: RidgeRow[];
}

// ── Geometry constants (identical to mockup buildRidge) ──────────────────────
// Geometry tuned for a tall half-width panel (the combined "shape of the
// backlog" section places this beside the heatmap) rather than a wide
// full-bleed strip. Narrower W + more vertical room per decade; total height
// scales with the row count (see `H` in the component).
const W = 680;
const padL = 56;
const padR = 18;
const plotW = W - padL - padR; // 606
const topY = 50;
const stepY = 40;
const amp = 50;
const N = 140; // kde sample count

// ── KDE: same gaussian as mockup ─────────────────────────────────────────────
interface KdePeak { mu: number; sig: number; w: number; }

function kde(peaks: KdePeak[], domainW: number, n: number): number[] {
  const d: number[] = [];
  for (let i = 0; i <= n; i++) {
    const x = (i / n) * domainW;
    let v = 0;
    for (const p of peaks) {
      const z = (x - p.mu * domainW) / (p.sig * domainW);
      v += p.w * Math.exp(-0.5 * z * z);
    }
    d.push(v);
  }
  return d;
}

// ── Grayscale ramp (identical to mockup gray()) ───────────────────────────────
const GRAY_STOPS: Array<[number, number, number]> = [
  [22, 25, 31],
  [38, 43, 51],
  [60, 66, 76],
  [87, 96, 105],
  [124, 134, 147],
  [170, 178, 189],
];

function grayAt(t: number): string {
  const idx = Math.min(GRAY_STOPS.length - 1, Math.floor(t * (GRAY_STOPS.length - 1)));
  const stop = GRAY_STOPS[idx] ?? GRAY_STOPS[GRAY_STOPS.length - 1]!;
  return `rgb(${stop[0]},${stop[1]},${stop[2]})`;
}

// ── Axis tick positions (same as mockup) ──────────────────────────────────────
const AXIS_TICKS: { label: string; frac: number }[] = [
  { label: "1920", frac: 0 },
  { label: "1960", frac: 0.34 },
  { label: "2000", frac: 0.78 },
  { label: "2025", frac: 1 },
];

export function Ridgeline({ rows }: Props) {
  const peakLabel = rows.find(r => r.peak)?.label ?? "2010s";

  // Vertical extent scales with the number of decade rows so the chart fills a
  // tall panel instead of rendering as a thin wide strip at half-width.
  const axisY = topY + Math.max(rows.length - 1, 0) * stepY + 24;
  const H = axisY + 12;

  // Build SVG elements for each row (rendered back-to-front: last row first)
  const rowElements: React.ReactNode[] = [];

  for (let ri = rows.length - 1; ri >= 0; ri--) {
    const row = rows[ri];
    if (!row) continue;

    // c is the normalized center position for this row's kde peak
    const c = (ri + 0.5) / rows.length;
    const w = row.weight;

    const d = kde(
      [
        { mu: c, sig: 0.052, w },
        { mu: c - 0.02, sig: 0.13, w: w * 0.28 },
      ],
      plotW,
      N,
    );

    const mx = Math.max(...d) || 1;
    const y0 = topY + ri * stepY;

    // Build the polyline path string
    let linePath = "";
    for (let i = 0; i < d.length; i++) {
      const val = d[i] ?? 0;
      const x = padL + (i / (d.length - 1)) * plotW;
      const y = y0 - (val / mx) * amp;
      linePath += `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `;
    }

    const fillPath = `M${padL},${y0} ${linePath}L${padL + plotW},${y0} Z`;

    if (row.peak) {
      rowElements.push(
        <path key={`fill-${ri}`} d={fillPath} fill="var(--accent)" fillOpacity={0.16} />,
        <path
          key={`line-${ri}`}
          className="ridge-line"
          d={linePath}
          fill="none"
          stroke="var(--accent-2)"
          strokeWidth={1.7}
        />,
      );
    } else {
      const grayStroke = grayAt(0.35 + ri * 0.045);
      rowElements.push(
        <path key={`fill-${ri}`} d={fillPath} fill="rgba(40,45,53,.55)" />,
        <path
          key={`line-${ri}`}
          d={linePath}
          fill="none"
          stroke={grayStroke}
          strokeWidth={1.2}
        />,
      );
    }

    // Decade label (left of padL)
    rowElements.push(
      <text
        key={`label-${ri}`}
        className="rlabel"
        x={padL - 12}
        y={y0 - 3}
        textAnchor="end"
        fontFamily="var(--font-mono)"
        fontSize={9.5}
        fill="var(--muted-foreground)"
      >
        {row.label}
      </text>,
    );
  }

  // Year axis
  const axisLabels = AXIS_TICKS.map(tick => (
    <text
      key={tick.label}
      className="raxis"
      x={padL + tick.frac * plotW}
      y={axisY}
      textAnchor="middle"
      fontFamily="var(--font-mono)"
      fontSize={9}
      fill="var(--muted-foreground)"
    >
      {tick.label}
    </text>
  ));

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={`Incidence density of unsolved cases by decade, peaking in the ${peakLabel}.`}
    >
      {rowElements}
      {axisLabels}
    </svg>
  );
}
