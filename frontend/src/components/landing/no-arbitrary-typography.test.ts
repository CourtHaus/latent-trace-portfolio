import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * Design-token guard (frontend audit 2026-06-09, Stage 4). After the snap to
 * the tokenized scale, the landing surfaces + shared primitives must not
 * reintroduce fixed arbitrary typography (`text-[13px]`, `tracking-[.16em]`,
 * `leading-[1.6]`). Fluid/computed values (`clamp()`, `calc()`, `var()`) are
 * allowed — they're intentional, not off-scale one-offs. Snap to the scale
 * instead: text-2xs/xs/sm/…, tracking-eyebrow/snug/wide…, leading-none/normal/…
 */
const ROOTS = ["src/components/landing", "src/components/site/primitives.tsx"];
// text-[ / tracking-[ / leading-[ NOT preceded by a word char (so `context-[`
// is ignored) and NOT immediately a clamp()/calc()/var().
const BANNED = /(?<![\w-])(text|tracking|leading)-\[(?!clamp|calc|var)/;

function collect(path: string): string[] {
  const abs = resolve(process.cwd(), path);
  const st = statSync(abs);
  if (st.isFile()) return abs.endsWith(".tsx") ? [abs] : [];
  return readdirSync(abs).flatMap((e) => collect(join(path, e)));
}

describe("design tokens: no fixed arbitrary typography in landing/primitives", () => {
  const files = ROOTS.flatMap(collect).filter((f) => !f.endsWith(".test.tsx"));

  it("covers the migrated surfaces", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  for (const file of files) {
    it(`${file.split("/frontend/")[1] ?? file} uses scale tokens, not bracket typography`, () => {
      const offenders = readFileSync(file, "utf8")
        .split("\n")
        .map((line, i) => ({ line: line.trim(), n: i + 1 }))
        .filter(({ line }) => BANNED.test(line));
      expect(
        offenders,
        `Use a scale token (text-2xs/xs/sm…, tracking-eyebrow/snug…, leading-none/normal…) instead of fixed bracket typography:\n` +
          offenders.map((o) => `  L${o.n}: ${o.line}`).join("\n"),
      ).toEqual([]);
    });
  }
});
