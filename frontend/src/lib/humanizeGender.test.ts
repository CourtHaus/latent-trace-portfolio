import { describe, it, expect } from "vitest";
import { humanizeGender } from "./humanizeGender";

describe("humanizeGender", () => {
  it("maps codes and full words to display labels (case-insensitive)", () => {
    expect(humanizeGender("M")).toBe("Male");
    expect(humanizeGender("male")).toBe("Male");
    expect(humanizeGender("F")).toBe("Female");
    expect(humanizeGender("Female")).toBe("Female");
    expect(humanizeGender("unknown")).toBe("Unknown");
  });
  it("returns null for null", () => {
    expect(humanizeGender(null)).toBeNull();
  });
  it("passes unrecognized values through unchanged", () => {
    expect(humanizeGender("nonbinary")).toBe("nonbinary");
  });
});
