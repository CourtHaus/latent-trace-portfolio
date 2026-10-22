import { describe, it, expect } from "vitest";
import { toRidgeRows } from "./decadeHistogram";

describe("toRidgeRows", () => {
  it("maps decade buckets to normalized rows with a peak flag", () => {
    const rows = toRidgeRows([
      { decade: 1990, count: 82 }, { decade: 2000, count: 95 }, { decade: 2010, count: 100 },
    ]);
    expect(rows).toHaveLength(3);
    expect(rows.find(r => r.peak)?.label).toBe("2010s");
    expect(Math.max(...rows.map(r => r.weight))).toBe(1);
  });
  it("preserves raw counts so callers can render real totals/peaks", () => {
    const rows = toRidgeRows([
      { decade: 1990, count: 82 }, { decade: 2000, count: 95 }, { decade: 2010, count: 100 },
    ]);
    expect(rows.reduce((s, r) => s + r.count, 0)).toBe(277);
    expect(rows.find(r => r.peak)?.count).toBe(100);
  });
});
