import { describe, it, expect } from "vitest";
import { mapUrlParsers } from "./mapUrlState";

describe("mapUrlParsers", () => {
  it("exposes the expected filter keys", () => {
    expect(Object.keys(mapUrlParsers).sort()).toEqual([
      "bbox",
      "case_type",
      "city",
      "gender",
      "location_type",
      "precision",
      "q",
      "race",
      "sort",
      "source_system",
      "weapon",
      "year_max",
      "year_min",
      "zoom",
    ]);
  });

  it("year_min parses integer strings", () => {
    expect(mapUrlParsers.year_min.parse("1998")).toBe(1998);
    expect(mapUrlParsers.year_min.parse("")).toBe(null);
  });

  it("zoom parses integer strings", () => {
    expect(mapUrlParsers.zoom.parse("9")).toBe(9);
    expect(mapUrlParsers.zoom.parse("")).toBe(null);
  });

  it("case_type parses comma-separated strings into arrays", () => {
    expect(mapUrlParsers.case_type.parse("homicide,missing-person")).toEqual([
      "homicide",
      "missing-person",
    ]);
    expect(mapUrlParsers.case_type.parse("homicide")).toEqual(["homicide"]);
  });

  it("case_type serializes arrays back to comma-separated strings", () => {
    expect(mapUrlParsers.case_type.serialize(["homicide", "missing-person"])).toBe(
      "homicide,missing-person",
    );
    expect(mapUrlParsers.case_type.serialize(["homicide"])).toBe("homicide");
  });

  it("bbox parses and serializes as an opaque string", () => {
    expect(mapUrlParsers.bbox.parse("-80,37,-77,39")).toBe("-80,37,-77,39");
    expect(mapUrlParsers.bbox.serialize("-80,37,-77,39")).toBe("-80,37,-77,39");
  });
});
