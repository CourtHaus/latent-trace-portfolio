import { describe, expect, it } from "vitest";
import { humanizeCaseType } from "./humanizeCaseType";

describe("humanizeCaseType", () => {
  it("renders homicide as 'Homicide'", () => {
    expect(humanizeCaseType("homicide")).toBe("Homicide");
  });
  it("renders suspicious_death as 'Suspicious Death'", () => {
    expect(humanizeCaseType("suspicious_death")).toBe("Suspicious Death");
  });
  it("titlecases unknown values", () => {
    expect(humanizeCaseType("missing_person")).toBe("Missing Person");
  });
  it("handles empty string", () => {
    expect(humanizeCaseType("")).toBe("");
  });
});
