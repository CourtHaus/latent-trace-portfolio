import { describe, it, expect } from "vitest";
import { buildCoverageMatrix, DECADE_COLS, DECADE_LABELS } from "./coverageMatrix";

const B = (state: string, decade: number, count: number) => ({ state, decade, count });

describe("buildCoverageMatrix", () => {
  it("orders states by total count desc and aligns counts to the 7 decade columns", () => {
    const { rows, values } = buildCoverageMatrix([
      B("OH", 2010, 100), B("OH", 2000, 50),
      B("CO", 2010, 40),
    ]);
    expect(rows).toEqual(["OH", "CO"]); // OH total 150 > CO 40
    const oh2010 = values[0]![DECADE_COLS.indexOf(2010)];
    expect(oh2010).toBe(1);
    expect(values[1]![DECADE_COLS.indexOf(2010)]).toBeCloseTo(0.4, 5);
  });
  it("folds pre-1960 decades into the 1960 column", () => {
    const { rows, values } = buildCoverageMatrix([
      B("ZZ", 1930, 3), B("ZZ", 1950, 2), B("ZZ", 1960, 5),
    ]);
    expect(rows).toEqual(["ZZ"]);
    expect(values[0]![DECADE_COLS.indexOf(1960)]).toBe(1);
  });
  it("normalizes by the GLOBAL max cell even when it lives in a non-first row", () => {
    // OH leads the ordering (total 200), but the single largest CELL is CO's 2010
    // value (150), which sits in the second row. Normalization must divide every
    // cell by 150, not by each row's own max (a per-row bug would make both 2010
    // cells equal 1).
    const { rows, values } = buildCoverageMatrix([
      B("OH", 2010, 100), B("OH", 2000, 100),
      B("CO", 2010, 150),
    ]);
    expect(rows).toEqual(["OH", "CO"]); // OH total 200 > CO total 150
    const c2010 = DECADE_COLS.indexOf(2010);
    expect(values[1]![c2010]).toBe(1); // CO 2010 = 150/150 (global max, row 1)
    expect(values[0]![c2010]).toBeCloseTo(100 / 150, 5); // OH 2010 = 100/150, NOT 1
  });
  it("breaks total-count ties by first-seen order (stable sort)", () => {
    const { rows } = buildCoverageMatrix([
      B("MD", 1990, 10), B("DC", 1990, 10),
    ]);
    expect(rows).toEqual(["MD", "DC"]); // equal totals -> insertion order preserved
  });
  it("returns empty rows/values for empty input", () => {
    expect(buildCoverageMatrix([])).toEqual({ rows: [], values: [] });
  });
  it("exposes 7 decade labels", () => {
    expect(DECADE_LABELS).toEqual(["60s", "70s", "80s", "90s", "00s", "10s", "20s"]);
  });
});
