import type { RidgeRow } from "@/lib/decadeHistogram";

interface Props {
  rows: RidgeRow[];
}

// ── Geometry constants (identical to mockup heroRidge) ───────────────────────
const W = 760;
const stepY = 30;
const topY = 70;
const amp = 82;
const N = 120; // kde sample count

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

const MASK = "linear-gradient(90deg, transparent, #000 42%)";

export function HeroRidge({ rows }: Props) {
  const rowElements: React.ReactNode[] = [];

  for (let ri = rows.length - 1; ri >= 0; ri--) {
    const row = rows[ri];
    if (!row) continue;

    const c = (ri + 0.5) / rows.length;
    const w = row.weight;

    const d = kde(
      [
        { mu: c, sig: 0.06, w },
        { mu: c - 0.03, sig: 0.15, w: w * 0.3 },
      ],
      W,
      N,
    );

    const mx = Math.max(...d) || 1;
    const y0 = topY + ri * stepY;

    let linePath = "";
    for (let i = 0; i < d.length; i++) {
      const val = d[i] ?? 0;
      const x = (i / (d.length - 1)) * W;
      const y = y0 - (val / mx) * amp;
      linePath += `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `;
    }

    const fillPath = `M0,${y0} ${linePath}L${W},${y0} Z`;

    if (row.peak) {
      rowElements.push(
        <path key={`fill-${ri}`} d={fillPath} fill="var(--accent)" fillOpacity={0.14} />,
        <path
          key={`line-${ri}`}
          d={linePath}
          fill="none"
          stroke="var(--accent-2)" strokeOpacity={0.85}
          strokeWidth={1.4}
        />,
      );
    } else {
      const alpha = (0.18 + ri * 0.03).toFixed(2);
      rowElements.push(
        <path key={`fill-${ri}`} d={fillPath} fill="rgba(28,32,39,.5)" />,
        <path
          key={`line-${ri}`}
          d={linePath}
          fill="none"
          stroke={`rgba(110,120,134,${alpha})`}
          strokeWidth={1}
        />,
      );
    }
  }

  // Derived viewBox height: topY + (rows.length - 1) * stepY + amp + small margin
  const viewH = topY + Math.max(0, rows.length - 1) * stepY + amp + 30;

  return (
    <svg
      viewBox={`0 0 ${W} ${viewH}`}
      preserveAspectRatio="xMidYMax meet"
      aria-hidden="true"
      style={{
        WebkitMaskImage: MASK,
        maskImage: MASK,
      }}
    >
      {rowElements}
    </svg>
  );
}
