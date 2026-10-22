// JointPlot: joint distribution scatter (distance x years apart) + ranked leads list.
//
// Prop conventions:
//   point.distance  : 0..1  (0 = focal case, 1 = 50 mi boundary)
//   point.yearsApart: 0..1  (0 = same year, 1 = 20 yr boundary)
//   point.score     : 0..1  (correlation score; higher = stronger lead)
//   lead.distanceMi : raw miles (displayed as "N mi")
//   lead.yearsApart : raw years (displayed as "N yr")
//   lead.score      : 0..1
//
// SAMPLE_CORRELATION is the deterministic Phase-1 exemplar.
// All scatter points are hard-coded; no Math.random() is used anywhere in this file.

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ScatterPoint {
  distance: number;    // 0..1 normalized
  yearsApart: number;  // 0..1 normalized
  score: number;       // 0..1
}

export interface Lead {
  id: string;
  name: string;
  distanceMi: number;
  yearsApart: number;
  score: number;
}

export interface JointPlotProps {
  points: ScatterPoint[];
  leads: Lead[];
}

// ── Deterministic Phase-1 sample ──────────────────────────────────────────────
// Points are laid on a lattice skewed toward the origin (low distance + low years apart
// = high score region). Score = (1-distance)*(1-yearsApart), matching the mockup formula.
// Rows at d=0.06..0.90, cols at y=0.06..0.90, with an extra cluster near the origin.

function pt(d: number, y: number): ScatterPoint {
  return { distance: d, yearsApart: y, score: (1 - d) * (1 - y) };
}

export const SAMPLE_CORRELATION: JointPlotProps = {
  points: [
    // tight cluster near origin (high-confidence zone, d<0.4, y<0.4)
    pt(0.06, 0.07),
    pt(0.10, 0.14),
    pt(0.14, 0.06),
    pt(0.18, 0.22),
    pt(0.22, 0.10),
    pt(0.08, 0.30),
    pt(0.30, 0.08),
    pt(0.26, 0.20),
    pt(0.20, 0.34),
    pt(0.34, 0.16),
    pt(0.38, 0.28),
    pt(0.12, 0.38),
    pt(0.28, 0.36),
    pt(0.36, 0.38),
    // mid-range cluster (d=0.4-0.65, y=0.08-0.5)
    pt(0.44, 0.12),
    pt(0.48, 0.24),
    pt(0.52, 0.10),
    pt(0.56, 0.36),
    pt(0.42, 0.44),
    pt(0.60, 0.22),
    pt(0.64, 0.46),
    pt(0.46, 0.56),
    pt(0.50, 0.52),
    pt(0.54, 0.62),
    // scattered outer points
    pt(0.70, 0.18),
    pt(0.74, 0.38),
    pt(0.66, 0.60),
    pt(0.72, 0.64),
    pt(0.80, 0.28),
    pt(0.78, 0.50),
    pt(0.84, 0.42),
    pt(0.88, 0.22),
    pt(0.82, 0.68),
    pt(0.90, 0.56),
    // high y-axis points (wide time spread)
    pt(0.16, 0.58),
    pt(0.24, 0.70),
    pt(0.32, 0.76),
    pt(0.40, 0.80),
    pt(0.58, 0.82),
    pt(0.68, 0.88),
  ],

  leads: [
    { id: "CS-3920", name: "D. Castellano",     distanceMi: 12, yearsApart: 3,  score: 0.84 },
    { id: "CS-4101", name: "R. Mercer",          distanceMi: 19, yearsApart: 6,  score: 0.71 },
    { id: "CS-2884", name: "Unidentified male",  distanceMi: 8,  yearsApart: 11, score: 0.63 },
    { id: "CS-4012", name: "T. Whitfield",       distanceMi: 31, yearsApart: 4,  score: 0.52 },
    { id: "CS-1559", name: "A. Bowen",           distanceMi: 27, yearsApart: 13, score: 0.44 },
  ],
};

// ── Geometry constants (mirroring buildJoint from mockup) ─────────────────────
const W   = 560;
const H   = 400;
const mL  = 56;   // margin left
const mR  = 76;   // margin right (leaves room for right marginal KDE)
const mT  = 74;   // margin top (leaves room for top marginal KDE)
const mB  = 54;   // margin bottom
const pw  = W - mL - mR;  // plot width  = 428
const ph  = H - mT - mB;  // plot height = 272
const ox  = mL;            // origin x (focal case)
const oy  = mT + ph;       // origin y (focal case)

// ── Color helpers ─────────────────────────────────────────────────────────────
type RGB = [number, number, number];
const EM:  RGB = [217, 96,  63];
const EM2: RGB = [240, 133, 95];
const GY:  RGB = [92,  101, 112];
const GY_DIM: RGB = [44, 49, 57];

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}
function mixRgb(c1: RGB, c2: RGB, t: number): string {
  return `rgb(${Math.round(lerp(c1[0], c2[0], t))},${Math.round(lerp(c1[1], c2[1], t))},${Math.round(lerp(c1[2], c2[2], t))})`;
}

// ── Simple scalar KDE for marginal curves ─────────────────────────────────────
// Same gaussian kernel as buildJoint's skde(), bandwidth 0.12, n=72 samples.
function skde(vals: number[], bw: number): number[] {
  const n = 72;
  const d: number[] = [];
  for (let i = 0; i <= n; i++) {
    const x = i / n;
    let v = 0;
    for (const val of vals) {
      const u = (x - val) / bw;
      v += Math.exp(-0.5 * u * u);
    }
    d.push(v);
  }
  return d;
}

// ── Marginal density path builder ─────────────────────────────────────────────
// horiz=true → top marginal (over distance axis)
// horiz=false → right marginal (over years axis)
function buildMarginalPaths(vals: number[], horiz: boolean): { area: string; line: string } {
  const d = skde(vals, 0.12);
  const mx = Math.max(...d) || 1;
  const n = d.length - 1;
  const depth = 46; // px amplitude of the KDE curve
  let line = "";

  if (horiz) {
    for (let i = 0; i <= n; i++) {
      const x = mL + (i / n) * pw;
      const y = mT - 10 - ((d[i] ?? 0) / mx) * depth;
      line += `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `;
    }
    const area = `M${mL},${mT - 10} ${line}L${mL + pw},${mT - 10} Z`;
    return { area, line: line.trim() };
  } else {
    for (let i = 0; i <= n; i++) {
      const yy = mT + ph - (i / n) * ph;
      const xx = mL + pw + 10 + ((d[i] ?? 0) / mx) * depth;
      line += `${i === 0 ? "M" : "L"}${xx.toFixed(1)},${yy.toFixed(1)} `;
    }
    const area = `M${mL + pw + 10},${mT + ph} ${line}L${mL + pw + 10},${mT} Z`;
    return { area, line: line.trim() };
  }
}

// ── Scatter point SVG elements ─────────────────────────────────────────────────
function ScatterPoints({ points }: { points: ScatterPoint[] }) {
  const strongPoints = points.filter(p => p.score > 0.66);

  return (
    <>
      {/* Faint focal links from origin to strongest points */}
      {strongPoints.map((p, i) => {
        const cx = mL + p.distance * pw;
        const cy = mT + ph - p.yearsApart * ph;
        return (
          <line
            key={`link-${i}`}
            x1={ox}
            y1={oy}
            x2={cx.toFixed(1)}
            y2={cy.toFixed(1)}
            stroke="var(--accent)" strokeOpacity={0.2}
            strokeWidth={1}
          />
        );
      })}

      {/* Scatter circles */}
      {points.map((p, i) => {
        const cx = mL + p.distance * pw;
        const cy = mT + ph - p.yearsApart * ph;
        const strong = p.score > 0.66;
        const col = strong
          ? mixRgb(EM, EM2, (p.score - 0.66) / 0.34)
          : mixRgb(GY_DIM, GY, Math.min(1, p.score / 0.66));
        const r = strong ? 3.4 + p.score * 2.4 : 2.4 + p.score * 1.4;

        return (
          <g key={`pt-${i}`}>
            {/* Glow halo for strong leads */}
            {strong && (
              <circle
                cx={cx.toFixed(1)}
                cy={cy.toFixed(1)}
                r={(r + 3).toFixed(1)}
                fill="var(--accent)" fillOpacity={0.15}
              />
            )}
            <circle
              cx={cx.toFixed(1)}
              cy={cy.toFixed(1)}
              r={r.toFixed(1)}
              fill={col}
              opacity={strong ? 1 : 0.85}
            />
          </g>
        );
      })}
    </>
  );
}

// ── JointPlot SVG ──────────────────────────────────────────────────────────────
function JointSvg({ points }: { points: ScatterPoint[] }) {
  // Gridlines: 3 vertical + 3 horizontal (at 0, 0.5, 1.0 of each axis)
  const gridLines: React.ReactNode[] = [];
  for (let g = 0; g <= 2; g++) {
    const gx = mL + (g / 2) * pw;
    const gy = mT + (g / 2) * ph;
    gridLines.push(
      <line key={`gx-${g}`} x1={gx} y1={mT} x2={gx} y2={mT + ph} stroke="rgba(255,255,255,.045)" />,
      <line key={`gy-${g}`} x1={mL} y1={gy} x2={mL + pw} y2={gy} stroke="rgba(255,255,255,.045)" />,
    );
  }

  // Dashed high-confidence rect: 50%×50% of plot area from origin (40% of domain = 20mi/8yr)
  const hcX = mL;
  const hcY = mT + ph - 0.4 * ph;
  const hcW = (0.4 * pw).toFixed(1);
  const hcH = (0.4 * ph).toFixed(1);

  // Marginal KDE curves
  const topMarg  = buildMarginalPaths(points.map(p => p.distance), true);
  const rightMarg = buildMarginalPaths(points.map(p => p.yearsApart), false);

  return (
    <svg
      viewBox="0 0 560 400"
      width="100%"
      role="img"
      aria-label="Candidate cases with shared characteristics by distance and years apart; strongest correlations highlighted near the focal case."
    >
      {/* Gridlines */}
      {gridLines}

      {/* High-confidence zone */}
      <rect
        x={hcX}
        y={hcY}
        width={hcW}
        height={hcH}
        fill="var(--accent)" fillOpacity={0.05}
        stroke="var(--accent)" strokeOpacity={0.2}
        strokeDasharray="3 3"
      />
      <text
        x={mL + 6}
        y={hcY - 6}
        fill="#9a6a55"
        fontFamily="var(--font-mono)"
        fontSize={9}
      >
        high-confidence
      </text>

      {/* Plot axes */}
      <line x1={mL} y1={mT + ph} x2={mL + pw} y2={mT + ph} stroke="rgba(255,255,255,.14)" />
      <line x1={mL} y1={mT}      x2={mL}       y2={mT + ph} stroke="rgba(255,255,255,.14)" />

      {/* Scatter (links + points) */}
      <ScatterPoints points={points} />

      {/* Top marginal KDE (distance distribution) */}
      <path d={topMarg.area} fill="rgba(124,134,147,.15)" />
      <path d={topMarg.line} fill="none" stroke="#8b94a1" strokeWidth={1.2} />

      {/* Right marginal KDE (years-apart distribution) */}
      <path d={rightMarg.area} fill="rgba(124,134,147,.15)" />
      <path d={rightMarg.line} fill="none" stroke="#8b94a1" strokeWidth={1.2} />

      {/* Focal marker (origin) */}
      <circle cx={ox} cy={oy} r={7}   fill="#0c0e12" stroke="var(--accent)" strokeWidth={1.6} />
      <circle cx={ox} cy={oy} r={2.4} fill="var(--accent)" />
      <text
        x={ox + 11}
        y={oy - 9}
        fill="var(--accent-2)"
        fontFamily="var(--font-mono)"
        fontSize={9}
      >
        focal
      </text>

      {/* X-axis ticks: 0 / 25 mi / 50 mi */}
      <text x={mL}           y={mT + ph + 17} textAnchor="start"  fontFamily="var(--font-mono)" fontSize={9} fill="var(--muted-foreground,#8b94a1)">0</text>
      <text x={mL + pw / 2}  y={mT + ph + 17} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={9} fill="var(--muted-foreground,#8b94a1)">25 mi</text>
      <text x={mL + pw}      y={mT + ph + 17} textAnchor="end"    fontFamily="var(--font-mono)" fontSize={9} fill="var(--muted-foreground,#8b94a1)">50 mi</text>
      <text x={mL + pw / 2}  y={H - 12}       textAnchor="middle" fontFamily="var(--font-mono)" fontSize={9} fill="var(--muted-foreground,#8b94a1)">distance from focal</text>

      {/* Y-axis ticks: 0 / 10 yr / 20 yr + rotated label */}
      <text x={mL - 9} y={mT + ph + 3}  textAnchor="end" fontFamily="var(--font-mono)" fontSize={9} fill="var(--muted-foreground,#8b94a1)">0</text>
      <text x={mL - 9} y={mT + ph / 2 + 3} textAnchor="end" fontFamily="var(--font-mono)" fontSize={9} fill="var(--muted-foreground,#8b94a1)">10</text>
      <text x={mL - 9} y={mT + 8}       textAnchor="end" fontFamily="var(--font-mono)" fontSize={9} fill="var(--muted-foreground,#8b94a1)">20</text>
      <text
        x={16}
        y={mT + ph / 2}
        textAnchor="middle"
        transform={`rotate(-90 16 ${mT + ph / 2})`}
        fontFamily="var(--font-mono)"
        fontSize={9}
        fill="var(--muted-foreground,#8b94a1)"
      >
        years apart
      </text>
    </svg>
  );
}

// ── RankedLeads ───────────────────────────────────────────────────────────────
// Exported separately so a parent layout can render leads beside the plot.
export function RankedLeads({ leads }: { leads: Lead[] }) {
  return (
    <div>
      {leads.map(lead => (
        <div
          key={lead.id}
          style={{
            padding: "13px 18px",
            borderBottom: "1px solid rgba(255,255,255,.05)",
          }}
        >
          {/* Top row: id + name + proximity */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span>
              <span
                style={{
                  fontFamily: "var(--font-mono, monospace)",
                  fontSize: "10.5px",
                  color: "var(--muted-foreground, #586270)",
                  marginRight: 8,
                }}
              >
                {lead.id}
              </span>
              <span style={{ fontWeight: 500 }}>{lead.name}</span>
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono, monospace)",
                fontSize: "10.5px",
                color: "var(--muted-foreground, #8b94a1)",
              }}
            >
              {lead.distanceMi} mi · {lead.yearsApart} yr
            </span>
          </div>

          {/* Score bar + tabular score */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 9 }}>
            <span
              style={{
                height: 5,
                flex: 1,
                background: "rgba(255,255,255,.06)",
                borderRadius: 3,
                overflow: "hidden",
                display: "block",
              }}
            >
              <span
                style={{
                  display: "block",
                  height: "100%",
                  width: `${lead.score * 100}%`,
                  background: "linear-gradient(90deg,var(--accent),var(--accent-2))",
                  borderRadius: 3,
                }}
              />
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono, monospace)",
                fontSize: 11,
                color: "var(--accent)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {lead.score.toFixed(2)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── JointScatter (SVG only, no leads list) ────────────────────────────────────
// Exported separately so a parent layout can render the scatter and leads side-by-side
// without duplicating the leads list (the Correlation section uses this).
export function JointScatter({ points }: { points: ScatterPoint[] }) {
  return <JointSvg points={points} />;
}

// ── JointPlot (scatter + leads list) ──────────────────────────────────────────
export function JointPlot({ points, leads }: JointPlotProps) {
  return (
    <div>
      <JointSvg points={points} />
      <RankedLeads leads={leads} />
    </div>
  );
}
