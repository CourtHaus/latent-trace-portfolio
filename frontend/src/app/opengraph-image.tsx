import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";

// Generated social card. Replaces the old hand-baked public/og-default.png so
// the brand can never drift out of sync again: rename or re-hue and this card
// regenerates from the same tokens.
// The whole card renders in Pinnacle (the brand display face): wordmark in
// DemiBold (600), tagline in Regular (400). satori parses TTF/OTF (not woff2),
// so we read the bundled .ttf weights; once fonts are supplied satori has no
// built-in fallback, so every glyph must be covered by a provided weight.
// Accent + layout match the brand.
export const alt = "Latent Trace: open-access analytics for unsolved cold cases";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Brand tokens as hex (satori does not support oklch). Kept in sync with the
// :root block in globals.css.
const BG = "#05090D"; // --background  oklch(0.135 0.012 248)
const FG = "#E9EDF2"; // --foreground  oklch(0.945 0.008 248)
const MUTED = "#8B939C"; // --muted-foreground  oklch(0.66 0.016 248)
const ACCENT = "#FF671A"; // --primary  oklch(0.6977 0.2010 42.06)

export default async function OpengraphImage() {
  const fontDir = join(process.cwd(), "src/fonts/pinnacle");
  const [pinnacleDemiBold, pinnacleRegular] = await Promise.all([
    readFile(join(fontDir, "Pinnacle-DemiBold.ttf")),
    readFile(join(fontDir, "Pinnacle-Regular.ttf")),
  ]);

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          backgroundColor: BG,
          padding: "96px",
        }}
      >
        {/* Wordmark: fingerprint glyph (concentric arches, brand kit) + name */}
        <div style={{ display: "flex", alignItems: "center", gap: "30px" }}>
          <svg width="84" height="84" viewBox="0 0 100 100" fill={ACCENT}>
            <path d="m50 8.332c-11.051 0-21.648 4.3906-29.461 12.207-7.8164 7.8125-12.207 18.41-12.207 29.461v25h8.3359v-25c0-11.91 6.3516-22.914 16.664-28.867 10.316-5.9531 23.02-5.9531 33.336 0 10.312 5.9531 16.664 16.957 16.664 28.867v25h8.332l0.003907-25c0-11.051-4.3906-21.648-12.207-29.461-7.8125-7.8164-18.41-12.207-29.461-12.207z" />
            <path d="m50 20.832c-7.7344 0-15.152 3.0742-20.625 8.543-5.4688 5.4727-8.543 12.891-8.543 20.625v33.332h8.332l0.003907-33.332c0-7.4414 3.9688-14.32 10.414-18.043 6.4453-3.7227 14.391-3.7227 20.836 0 6.4453 3.7227 10.414 10.602 10.414 18.043v33.332h8.332l0.003907-33.332c0-7.7344-3.0742-15.152-8.543-20.625-5.4727-5.4688-12.891-8.543-20.625-8.543z" />
            <path d="m50 33.332c-4.4219 0-8.6602 1.7578-11.785 4.8828s-4.8828 7.3633-4.8828 11.785v41.668h8.332l0.003907-41.668c0-4.6016 3.7305-8.332 8.332-8.332s8.332 3.7305 8.332 8.332v41.668h8.332l0.003907-41.668c0-4.4219-1.7578-8.6602-4.8828-11.785s-7.3633-4.8828-11.785-4.8828z" />
            <path d="m45.832 50h8.332v41.668h-8.332z" />
          </svg>
          <div
            style={{
              fontFamily: "Pinnacle",
              fontSize: "96px",
              fontWeight: 600,
              color: FG,
              letterSpacing: "0.01em",
            }}
          >
            Latent Trace
          </div>
        </div>

        {/* Tagline */}
        <div
          style={{
            display: "flex",
            fontFamily: "Pinnacle",
            fontWeight: 400,
            marginTop: "40px",
            fontSize: "42px",
            color: MUTED,
            letterSpacing: "0.005em",
          }}
        >
          Open-access analytics for unsolved cold cases
        </div>

        {/* Accent baseline */}
        <div
          style={{
            display: "flex",
            marginTop: "64px",
            width: "180px",
            height: "8px",
            borderRadius: "4px",
            backgroundColor: ACCENT,
          }}
        />
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Pinnacle", data: pinnacleRegular, weight: 400, style: "normal" },
        { name: "Pinnacle", data: pinnacleDemiBold, weight: 600, style: "normal" },
      ],
    },
  );
}
