import type { CoverageBucket } from "@/lib/getCoverageHistogram";

/** The 7 decade columns shown in the heatmap (pre-1960 folds into 1960). */
export const DECADE_COLS = [1960, 1970, 1980, 1990, 2000, 2010, 2020] as const;
export const DECADE_LABELS = ["60s", "70s", "80s", "90s", "00s", "10s", "20s"];

function colIndex(decade: number): number {
  if (decade <= 1960) return 0; // fold pre-1960 into the 60s column
  const i = DECADE_COLS.indexOf(decade as (typeof DECADE_COLS)[number]);
  return i === -1 ? DECADE_COLS.length - 1 : i; // 2030+ (shouldn't occur) -> last
}

/**
 * Build the heatmap matrix from coverage buckets.
 * - rows = states ordered by total count desc (largest jurisdictions first)
 * - values[r][c] = count for (state, decade-col), normalized 0..1 by the global max cell
 */
export function buildCoverageMatrix(
  buckets: CoverageBucket[],
): { rows: string[]; values: number[][] } {
  if (buckets.length === 0) return { rows: [], values: [] };

  const byState = new Map<string, number[]>();
  const totals = new Map<string, number>();
  for (const b of buckets) {
    let row = byState.get(b.state);
    if (!row) {
      row = new Array<number>(DECADE_COLS.length).fill(0);
      byState.set(b.state, row);
    }
    const c = colIndex(b.decade);
    row[c] = (row[c] ?? 0) + b.count;
    totals.set(b.state, (totals.get(b.state) ?? 0) + b.count);
  }
  const rows = [...byState.keys()].sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0));
  const max = Math.max(1, ...[...byState.values()].flat());
  const values = rows.map((s) => byState.get(s)!.map((n) => n / max));
  return { rows, values };
}
