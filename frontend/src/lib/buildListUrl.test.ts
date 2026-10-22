import { describe, it, expect } from "vitest";
import { buildListUrl } from "./buildListUrl";

describe("buildListUrl", () => {
  it("returns '/cold-cases' with no params and no overrides", () => {
    expect(buildListUrl({}, {})).toBe("/cold-cases");
  });

  it("preserves existing filter params when overriding only page", () => {
    const result = buildListUrl(
      { year_min: "1990", gender: "Female,Male" },
      { page: 3 },
    );
    const parsed = new URL(`http://x${result}`);
    expect(parsed.pathname).toBe("/cold-cases");
    expect(parsed.searchParams.get("year_min")).toBe("1990");
    expect(parsed.searchParams.get("gender")).toBe("Female,Male");
    expect(parsed.searchParams.get("page")).toBe("3");
  });

  it("handles array values from Next searchParams (multi-set)", () => {
    const result = buildListUrl(
      { case_type: ["homicide", "missing-person"] },
      { page: 2 },
    );
    const parsed = new URL(`http://x${result}`);
    expect(parsed.searchParams.getAll("case_type")).toEqual(["homicide", "missing-person"]);
    expect(parsed.searchParams.get("page")).toBe("2");
  });

  it("setting an override to null removes the key", () => {
    const result = buildListUrl(
      { page: "5", year_min: "1990" },
      { page: null },
    );
    const parsed = new URL(`http://x${result}`);
    expect(parsed.searchParams.get("page")).toBeNull();
    expect(parsed.searchParams.get("year_min")).toBe("1990");
  });

  it("setting page to 1 keeps it in URL (explicit)", () => {
    const result = buildListUrl({}, { page: 1 });
    expect(result).toBe("/cold-cases?page=1");
  });

  it("skips undefined param values from the source", () => {
    const result = buildListUrl(
      { year_min: undefined, city: "Richmond" },
      {},
    );
    const parsed = new URL(`http://x${result}`);
    expect(parsed.searchParams.get("year_min")).toBeNull();
    expect(parsed.searchParams.get("city")).toBe("Richmond");
  });

  it("skips empty string values from the source", () => {
    const result = buildListUrl({ city: "" }, { page: 2 });
    const parsed = new URL(`http://x${result}`);
    expect(parsed.searchParams.get("city")).toBeNull();
    expect(parsed.searchParams.get("page")).toBe("2");
  });
});
