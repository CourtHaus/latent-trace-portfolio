// @vitest-environment node

import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

import sitemap from "./sitemap";
import { apiFetch } from "@/lib/api";

describe("sitemap", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    // The resilience paths log to console.error on purpose; keep test output clean.
    vi.spyOn(console, "error").mockImplementation(() => {});
    process.env.NEXT_PUBLIC_SITE_URL = "https://casesignal.example";
  });

  it("emits home + list + one entry per case", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      meta: { total: 2, offset: 0, limit: 1000 },
      data: [
        { case_id: 1, slug: "jane-doe-richmond-va-1998", case_name: "Jane Doe", case_type: "homicide", incident_date: "1998-05-14", city: "Richmond", state: "VA" },
        { case_id: 2, slug: "john-roe-norfolk-va", case_name: "John Roe", case_type: "missing-person", incident_date: null, city: "Norfolk", state: "VA" },
      ],
    });

    const entries = await sitemap();
    const urls = entries.map((e) => e.url);
    expect(urls).toContain("https://casesignal.example/");
    expect(urls).toContain("https://casesignal.example/cold-cases");
    expect(urls).toContain("https://casesignal.example/cold-cases/map");
    expect(urls).toContain("https://casesignal.example/methodology");
    expect(urls).toContain("https://casesignal.example/about");
    expect(urls).toContain("https://casesignal.example/privacy");
    expect(urls).toContain("https://casesignal.example/terms");
    expect(urls).toContain("https://casesignal.example/cold-cases/1/jane-doe-richmond-va-1998");
    expect(urls).toContain("https://casesignal.example/cold-cases/2/john-roe-norfolk-va");
    expect(entries).toHaveLength(9);
  });

  it("paginates past the first page until a short page", async () => {
    const makeCase = (i: number) => ({
      case_id: i,
      slug: `case-${i}`,
      case_name: `Case ${i}`,
      case_type: "homicide",
      incident_date: null,
      city: "X",
      state: "VA",
    });
    const fullPage = Array.from({ length: 1000 }, (_, i) => makeCase(i + 1));
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ meta: { total: 1001, offset: 0, limit: 1000 }, data: fullPage })
      .mockResolvedValueOnce({
        meta: { total: 1001, offset: 1000, limit: 1000 },
        data: [makeCase(1001)],
      });

    const entries = await sitemap();
    const urls = entries.map((e) => e.url);
    // A full first page must trigger a second fetch; a short page stops it.
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(urls).toContain("https://casesignal.example/cold-cases/1001/case-1001");
    expect(entries).toHaveLength(7 + 1001); // 7 static + all cases
  });

  it("falls back to localhost when NEXT_PUBLIC_SITE_URL is unset", async () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    vi.mocked(apiFetch).mockResolvedValue({
      meta: { total: 0, offset: 0, limit: 1000 },
      data: [],
    });
    const entries = await sitemap();
    expect(entries[0]?.url).toBe("http://localhost:3000/");
  });

  const oneCase = {
    case_id: 1,
    slug: "jane-doe-richmond-va-1998",
    case_name: "Jane Doe",
    case_type: "homicide",
    incident_date: "1998-05-14",
    city: "Richmond",
    state: "VA",
  };

  it("retries a transient page failure and recovers", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(apiFetch)
        .mockRejectedValueOnce(new Error("transient 500"))
        .mockResolvedValueOnce({ meta: { total: 1, offset: 0, limit: 1000 }, data: [oneCase] });
      const p = sitemap();
      await vi.runAllTimersAsync();
      const entries = await p;
      // one failed attempt + one successful retry on the same (first) page
      expect(apiFetch).toHaveBeenCalledTimes(2);
      expect(entries.map((e) => e.url)).toContain(
        "https://casesignal.example/cold-cases/1/jane-doe-richmond-va-1998",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("degrades to a partial sitemap when a later page fails after retries", async () => {
    vi.useFakeTimers();
    try {
      const fullPage = Array.from({ length: 1000 }, (_, i) => ({
        case_id: i + 1,
        slug: `case-${i + 1}`,
        case_name: `Case ${i + 1}`,
        case_type: "homicide",
        incident_date: null,
        city: "X",
        state: "VA",
      }));
      vi.mocked(apiFetch)
        .mockResolvedValueOnce({ meta: { total: 2000, offset: 0, limit: 1000 }, data: fullPage })
        .mockRejectedValue(new Error("API down on page 1"));
      const p = sitemap();
      await vi.runAllTimersAsync();
      const entries = await p;
      // page 0 succeeds (1 call); page 1 exhausts all retries (3 calls)
      expect(apiFetch).toHaveBeenCalledTimes(1 + 3);
      // 7 static routes + the 1000 cases from page 0; build does NOT fail
      expect(entries).toHaveLength(7 + 1000);
    } finally {
      vi.useRealTimers();
    }
  });

  it("throws if the first page is unreachable (never ships a case-less sitemap)", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(apiFetch).mockRejectedValue(new Error("API down"));
      const p = sitemap();
      p.catch(() => {}); // pre-attach so the rejection isn't flagged unhandled
      await vi.runAllTimersAsync();
      await expect(p).rejects.toThrow(/first page/);
      expect(apiFetch).toHaveBeenCalledTimes(3); // all retries on page 0
    } finally {
      vi.useRealTimers();
    }
  });
});
