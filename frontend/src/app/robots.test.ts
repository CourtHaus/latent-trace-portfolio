// @vitest-environment node

import { describe, it, expect, beforeEach } from "vitest";
import robots from "./robots";

describe("robots", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://casesignal.example";
  });

  it("allows all + disallows /admin + crawlDelay + sitemap", () => {
    const r = robots();
    expect(r.rules).toEqual([
      { userAgent: "*", allow: "/", disallow: ["/admin"], crawlDelay: 10 },
    ]);
    expect(r.sitemap).toBe("https://casesignal.example/sitemap.xml");
  });
});
