import { vi, afterEach, expect } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { toHaveNoViolations } from "vitest-axe/dist/matchers";

// `server-only` throws at module load unless the `react-server` export
// condition is set. Next.js sets that condition per-module-graph for RSC;
// Vitest has no equivalent scoping. Setting it globally in resolve.conditions
// would also redirect `react` to its RSC-only build (no hooks, no events),
// breaking RTL render(). Mocking the package is targeted and is the pattern
// Next.js docs recommend for vitest setups.
vi.mock("server-only", () => ({}));

// lib/api.ts throws at module load if API_BASE_URL is missing.
// Tests stub fetch, but the env var must exist before the module is imported.
process.env.API_BASE_URL = "http://localhost:8000";

// RTL cleanup — globals: false in vitest.config.ts means RTL's auto-cleanup
// detection (typeof afterEach === 'function') fails. Register it explicitly.
afterEach(() => cleanup());

// vitest-axe matcher — the package's published `vitest-axe/extend-expect` and
// `vitest-axe/matchers` entrypoints have packaging issues (type-only re-exports).
// Import from dist/matchers as a workaround. `vitest-axe` is exact-pinned in
// package.json to prevent silent breakage on `pnpm update`; revisit if the
// upstream exports are fixed.
expect.extend({ toHaveNoViolations });

declare module "vitest" {
  // The `T = any` defaults must match vitest's own Assertion declaration
  // for interface merging to work — TS errors with "all declarations must
  // have identical type parameters" if we tighten to `unknown` here. Per-line
  // disables instead of file-wide.
  interface Assertion<T = any> {  // eslint-disable-line @typescript-eslint/no-explicit-any
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}
