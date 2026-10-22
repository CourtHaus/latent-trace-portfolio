import { describe, it, expect } from "vitest";
import { spawnSync } from "node:child_process";
import path from "node:path";

describe("smoke: production build", () => {
  it("pnpm build exits 0", () => {
    const result = spawnSync("pnpm", ["build"], {
      cwd: path.resolve(__dirname, ".."),
      encoding: "utf8",
      stdio: "pipe",
      env: {
        ...process.env,
        // api.ts throws at module load if API_BASE_URL is unset; the build
        // evaluates api.ts via the /cold-cases page. Without this, the build
        // fails with a "must be set" error even though the URL isn't hit.
        API_BASE_URL: process.env.API_BASE_URL ?? "http://localhost:8000",
      },
    });
    if (result.status !== 0) {
      console.error(result.stdout);
      console.error(result.stderr);
    }
    expect(result.status).toBe(0);
  }, 180_000);
});
