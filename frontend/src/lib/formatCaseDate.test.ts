import { describe, it, expect } from "vitest";
import { formatCaseDate } from "./formatCaseDate";

describe("formatCaseDate", () => {
  it("formats a full ISO date", () => {
    expect(formatCaseDate("1998-05-14")).toBe("May 14, 1998");
  });

  it("formats an ISO datetime", () => {
    expect(formatCaseDate("1998-05-14T00:00:00Z")).toBe("May 14, 1998");
  });

  it("returns the year for a year-only value", () => {
    expect(formatCaseDate("1998")).toBe("1998");
  });

  it("returns the year when month/day are zero placeholders", () => {
    expect(formatCaseDate("1998-00-00")).toBe("1998");
  });

  it("renders an em dash for null / empty / whitespace", () => {
    expect(formatCaseDate(null)).toBe("—");
    expect(formatCaseDate(undefined)).toBe("—");
    expect(formatCaseDate("")).toBe("—");
    expect(formatCaseDate("   ")).toBe("—");
  });

  it("does not shift the day across timezones", () => {
    expect(formatCaseDate("2006-01-01")).toBe("Jan 1, 2006");
  });

  it("passes through an unparseable value", () => {
    expect(formatCaseDate("circa 1990s")).toBe("circa 1990s");
  });
});
