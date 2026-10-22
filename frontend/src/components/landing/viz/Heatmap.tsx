import { Fragment } from "react";

// Heatmap: jurisdiction × decade record-density heatmap with ember colormap + colorbar.
//
// Port of the heatmap IIFE from docs/design/2026-06-07-latent-landing-mockup.html.
// Renders declaratively (map over rows/cols) so it SSRs; hover is the only client interaction.
//
// Props:
//   rows   — jurisdiction labels (e.g. ["OH", "CO", "DC", …])
//   cols   — decade labels    (e.g. ["60s", "70s", "80s", …])
//   values — row-major matrix of density values in 0..1

export interface HeatmapProps {
  rows: string[];
  cols: string[];
  /** Row-major matrix; values[r][c] must be in 0..1. */
  values: number[][];
}

// ── Colormap ──────────────────────────────────────────────────────────────────
// 5-stop RGB lerp: dark #14161b → brand orange #FF894D (--accent-2). Top stops
// track the Latent Trace brand kit (DESIGN.md): #E64D00 (color-500) → #FF894D.

type RGB = [number, number, number];

const EMBER_STOPS: RGB[] = [
  [20, 22, 27],
  [44, 47, 55],
  [110, 56, 34],
  [230, 77, 0],
  [255, 137, 77],
];

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/** Interpolate the 5-stop ember colormap at 0..1, returning an rgb() string. */
function ember(t: number): string {
  const s = EMBER_STOPS;
  const clamped = clamp01(t);
  const f = clamped * (s.length - 1);
  let i = Math.floor(f);
  let k = f - i;
  if (i >= s.length - 1) {
    i = s.length - 2;
    k = 1;
  }
  const a = s[i]!;
  const b = s[i + 1]!;
  const r = Math.round(a[0] + (b[0] - a[0]) * k);
  const g = Math.round(a[1] + (b[1] - a[1]) * k);
  const bv = Math.round(a[2] + (b[2] - a[2]) * k);
  return `rgb(${r},${g},${bv})`;
}

// Pre-compute the colorbar gradient string once (same call pattern as mockup).
const COLORBAR_GRADIENT = [
  `linear-gradient(to top, ${ember(0)}, ${ember(0.25)}, ${ember(0.5)}, ${ember(0.75)}, ${ember(1)})`,
].join("");

// ── Component ─────────────────────────────────────────────────────────────────

export function Heatmap({ rows, cols, values }: HeatmapProps) {
  // Grid: first column = row labels (40px), then one column per decade.
  const gridTemplateColumns = `40px repeat(${cols.length}, 1fr)`;

  return (
    <div
      style={{ display: "flex", gap: 18, alignItems: "stretch" }}
    >
      {/* Main grid */}
      <div
        role="img"
        aria-label="Record density by jurisdiction and decade."
        style={{
          flex: 1,
          display: "grid",
          gap: 4,
          gridTemplateColumns,
          maxWidth: 900,
          margin: "0 auto",
        }}
      >
        {/* Header row: empty corner + decade labels */}
        <div />
        {cols.map((col) => (
          <div
            key={col}
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "9.5px",
              color: "var(--color-faint)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {col}
          </div>
        ))}

        {/* Data rows */}
        {rows.map((row, ri) => (
          <Fragment key={row}>
            {/* Row label */}
            <div
              key={`label-${row}`}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "9.5px",
                color: "var(--color-faint)",
                display: "flex",
                alignItems: "center",
              }}
            >
              {row}
            </div>

            {/* Cells */}
            {cols.map((col, ci) => {
              const t = values[ri]?.[ci] ?? 0;
              return (
                <HeatCell
                  key={`${row}-${col}`}
                  background={ember(t)}
                  title={`${row} · ${col} · ${Math.round(t * 100)}`}
                />
              );
            })}
          </Fragment>
        ))}
      </div>

      {/* Colorbar */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 7,
          paddingTop: 22,
          paddingBottom: 2,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "8.5px",
            color: "var(--color-faint)",
          }}
        >
          high
        </span>
        <div
          style={{
            width: 9,
            flex: 1,
            borderRadius: 3,
            border: "1px solid rgba(255,255,255,.08)",
            background: COLORBAR_GRADIENT,
          }}
        />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "8.5px",
            color: "var(--color-faint)",
          }}
        >
          low
        </span>
      </div>
    </div>
  );
}

// ── Cell ──────────────────────────────────────────────────────────────────────

interface HeatCellProps {
  background: string;
  title: string;
}

function HeatCell({ background, title }: HeatCellProps) {
  return (
    <div
      className="hm-cell"
      title={title}
      style={{
        display: "block",
        borderRadius: 3,
        height: 28,
        background,
      }}
    />
  );
}
