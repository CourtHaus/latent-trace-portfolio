// @vitest-environment node
//
// next.config.ts calls withSentryConfig at module scope. Under the default
// jsdom environment Vitest puts @sentry/nextjs through its web transform, and
// the plugin @sentry/nextjs 10.71+ vendors runs `fileURLToPath(import.meta.url)`
// at import time — which throws "The URL must be of scheme file" once the URL
// is no longer a real file path. Nothing here needs a DOM: the subject is a
// plain Node config object, so the node environment is both the correct
// environment and the fix.
import { describe, expect, it, vi } from "vitest";

async function loadHeaders(apiBaseUrl: string, nodeEnv = "test") {
  vi.resetModules();
  process.env.API_BASE_URL = apiBaseUrl;
  // isProduction (which gates 'unsafe-eval') is computed at module load.
  vi.stubEnv("NODE_ENV", nodeEnv);
  try {
    const mod = await import("../next.config");
    const headers = await mod.default.headers?.();
    return { config: mod.default, headers: headers?.[0]?.headers ?? [] };
  } finally {
    vi.unstubAllEnvs();
  }
}

async function loadCspWithApiBase(
  apiBaseUrl: string,
  nodeEnv = "test",
): Promise<string> {
  const { headers } = await loadHeaders(apiBaseUrl, nodeEnv);
  const csp = headers.find((h) => h.key === "Content-Security-Policy");
  if (!csp) throw new Error("expected enforcing CSP header");
  return csp.value;
}

async function loadRewrites(apiBaseUrl: string) {
  vi.resetModules();
  process.env.API_BASE_URL = apiBaseUrl;
  const mod = await import("../next.config");
  return (await mod.default.rewrites?.()) ?? [];
}

describe("next security headers", () => {
  it("allows configured tunnel origins in dev mode", async () => {
    vi.resetModules();
    process.env.ALLOWED_DEV_ORIGINS = "tainted-grief-distract.ngrok-free.dev";
    const mod = await import("../next.config");

    expect(mod.default.allowedDevOrigins).toEqual([
      "tainted-grief-distract.ngrok-free.dev",
    ]);
  });

  it("allows the configured API origin in img-src in development (direct-origin photos)", async () => {
    const csp = await loadCspWithApiBase("https://api.casesignal.example", "development");

    expect(csp).toContain("img-src");
    expect(csp).toContain("https://api.casesignal.example");
  });

  it("omits the API origin from img-src in production (photos are proxied same-origin)", async () => {
    const csp = await loadCspWithApiBase("https://api.casesignal.example", "production");

    const imgSrc = csp.split(";").find((d) => d.trim().startsWith("img-src"));
    expect(imgSrc).toBeDefined();
    // The backend host must not leak into the public production CSP.
    expect(imgSrc).not.toContain("https://api.casesignal.example");
    expect(imgSrc).toContain("'self'");
  });

  it("ships an ENFORCING CSP, not report-only (SEC-F01)", async () => {
    const { headers } = await loadHeaders("https://api.casesignal.example");

    expect(headers.find((h) => h.key === "Content-Security-Policy")).toBeDefined();
    expect(
      headers.find((h) => h.key === "Content-Security-Policy-Report-Only"),
    ).toBeUndefined();
  });

  it("omits 'unsafe-eval' from script-src in production (SEC-F01)", async () => {
    const csp = await loadCspWithApiBase("https://api.casesignal.example", "production");

    const scriptSrc = csp.split(";").find((d) => d.trim().startsWith("script-src"));
    expect(scriptSrc).toBeDefined();
    expect(scriptSrc).not.toContain("'unsafe-eval'");
  });

  it("keeps 'unsafe-eval' in script-src in development (dev server needs it)", async () => {
    const csp = await loadCspWithApiBase("https://api.casesignal.example", "development");

    const scriptSrc = csp.split(";").find((d) => d.trim().startsWith("script-src"));
    expect(scriptSrc).toContain("'unsafe-eval'");
  });

  it("allows Vercel Speed Insights' debug host only in development", async () => {
    const devCsp = await loadCspWithApiBase(
      "https://api.casesignal.example",
      "development",
    );
    const prodCsp = await loadCspWithApiBase(
      "https://api.casesignal.example",
      "production",
    );

    const dir = (csp: string, name: string) =>
      csp.split(";").find((d) => d.trim().startsWith(name));

    // Dev: the debug script + its beacon come from va.vercel-scripts.com.
    expect(dir(devCsp, "script-src")).toContain("https://va.vercel-scripts.com");
    expect(dir(devCsp, "connect-src")).toContain("https://va.vercel-scripts.com");

    // Prod: Speed Insights is same-origin (/_vercel/...), so the host must NOT
    // leak into the enforcing production policy.
    expect(dir(prodCsp, "script-src")).not.toContain("va.vercel-scripts.com");
    expect(dir(prodCsp, "connect-src")).not.toContain("va.vercel-scripts.com");
  });

  it("does not advertise the framework via x-powered-by (SEC-F03)", async () => {
    const { config } = await loadHeaders("https://api.casesignal.example");
    expect(config.poweredByHeader).toBe(false);
  });

  it("proxies case photos through the configured API origin", async () => {
    const rewrites = await loadRewrites("https://api.casesignal.example");

    expect(rewrites).toContainEqual({
      source: "/api/v1/cold-cases/:caseId/photos/:filename",
      destination:
        "https://api.casesignal.example/api/v1/cold-cases/:caseId/photos/:filename",
    });
  });
});
