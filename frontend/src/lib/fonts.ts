import { Saira, Spline_Sans_Mono } from "next/font/google";
import localFont from "next/font/local";

export const saira = Saira({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

/**
 * Pinnacle — the Latent Trace brand display face (NASA-graphics-standards-inspired
 * geometric, SIL OFL 1.1, self-hosted from src/fonts/pinnacle). Drives
 * `--font-display` → `font-headline`, so it covers every headline and the
 * logo wordmark without touching body (Saira) or mono (Spline Sans Mono).
 */
export const pinnacle = localFont({
  src: [
    { path: "../fonts/pinnacle/Pinnacle-Regular.woff2", weight: "400", style: "normal" },
    { path: "../fonts/pinnacle/Pinnacle-Medium.woff2", weight: "500", style: "normal" },
    { path: "../fonts/pinnacle/Pinnacle-DemiBold.woff2", weight: "600", style: "normal" },
    { path: "../fonts/pinnacle/Pinnacle-Bold.woff2", weight: "700", style: "normal" },
    { path: "../fonts/pinnacle/Pinnacle-ExtraBold.woff2", weight: "800", style: "normal" },
  ],
  variable: "--font-display",
  display: "swap",
});

export const splineMono = Spline_Sans_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});
