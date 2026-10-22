---
version: alpha
name: "Latent Trace"
colors:
  primary: "#FF671A"
  dark: "#1F2937"
  white: "#FFFFFF"
  color-800: "#4D1A00"
  color-700: "#802B00"
  color-600: "#B33C00"
  color-500: "#E64D00"
  color-400: "#FF671A"
  color-300: "#FF894D"
  color-200: "#FFAA80"
  color-100: "#FFCCB3"
components:
  button-primary:
    backgroundColor: "{colors.color-600}"
    textColor: "{colors.white}"
  button-primary-hover:
    backgroundColor: "{colors.color-700}"
    textColor: "{colors.white}"
  button-secondary:
    backgroundColor: "{colors.white}"
    textColor: "{colors.color-600}"
  button-secondary-hover:
    backgroundColor: "{colors.white}"
    textColor: "{colors.color-700}"
---

## Overview

Brand assets for **Latent Trace**, serving [latenttrace.org](https://latenttrace.org).
The original brand kit credits [Anymark](https://anymark.co), dated 2026-06-10.
Keep that provenance when editing assets. The project rights notice does not
claim third-party rights or authorize reuse of another creator's work.

Use the tracked assets under [assets/](assets/). The original ZIP and social
cover exports are not required to build the application.

## Available assets

| File | Purpose |
| --- | --- |
| [latent_logo.svg](assets/latent_logo.svg) | Vector wordmark on a suitable light background |
| [latent_icon_color.png](assets/latent_icon_color.png) | Color icon |
| [latent_icon_white.png](assets/latent_icon_white.png) | White icon for dark backgrounds |
| [latent_favicon.ico](assets/latent_favicon.ico) | Browser favicon |

Use [frontend design tokens](../frontend/src/app/globals.css) for application
styling. The palette below records the brand-kit values; verify contrast in
the actual component before shipping. Contact
[courtney@latenttrace.org](mailto:courtney@latenttrace.org) for branding questions.

## Colors

### Primary tokens

- **primary** (`#FF671A`) — Primary brand color. CTAs, active states, highlights, key brand moments.
- **dark** (`#1F2937`) — Body text, borders, elements that need maximum readability.
- **white** (`#FFFFFF`) — Backgrounds, negative space, clean minimal layouts.

### Extended palette (generated shades)

- **color-800** (`#4D1A00`) — Darkest shade. Emphatic text on light.
- **color-700** (`#802B00`) — Active / pressed states, emphasis.
- **color-600** (`#B33C00`) — Hover state for primary CTAs.
- **color-500** (`#E64D00`) — Mid tone. Generic accents and fills.
- **color-400** (`#FF671A`) — Secondary accents. _(matches `primary` — the brand color)_
- **color-300** (`#FF894D`) — Disabled states, muted accents.
- **color-200** (`#FFAA80`) — Hover on light surfaces, dividers.
- **color-100** (`#FFCCB3`) — Lightest tint. Page backgrounds, subtle surfaces.

### Status badges

Any pairing of two colors from {primary, `color-100`–`color-700`, `#1F2937`, `#FFFFFF`} that reaches a 6:1 contrast ratio works as a badge. Typical pairs:

- Dark pill: background `#1F2937` or `color-800`, text `#FFFFFF` or a light palette tint.
- Tinted pill: background `color-100` / `color-200`, text `color-700` / `color-800`.
- Brand pill: background `primary` (`#FF671A`), text `#FFFFFF`. Only if the pair passes 6:1.

### Contrast note

Check WCAG AA contrast (4.5:1) before you ship. Anymark does not certify specific combinations.

## Components

Buttons are defined as tokens in the frontmatter above (`button-primary`, `button-primary-hover`, `button-secondary`, `button-secondary-hover`). Only `backgroundColor` and `textColor` are specified. Padding, radius, and typography are intentionally left to the consumer's design system.

We pick shades that hit WCAG AA contrast (4.5:1) against their paired text or background color. Verify before use. If the raw `primary` color does not pass 4.5:1 against white, the tokens reference a darker palette shade (`color-600`, `color-700`, or `color-800`) instead.

## Do's and Don'ts

### Do

- Use `latent_logo.svg` whenever the target supports vector. Fall back to PNG if any issues with SVG are found or if the customer requests it.
- Use `latent_icon_white.png` where an icon is appropriate on dark backgrounds.
- Keep clear space around the logo equal to at least the height of the icon.
- Reserve the `primary` color for primary CTAs, active states, and brand moments. Primary tokens (`primary`, `dark`, `white`) should cover ~80% of surfaces.
- Verify contrast when combining any two tokens from the extended palette.

### Don't

- Don't rotate the logo.
- Don't stretch, squash, or distort the proportions.
- Don't add gradients, shadows, outlines, or strokes to the logo.
- Don't recolor the logo outside this palette.
- Don't place the logo on low-contrast or visually cluttered backgrounds.
- Don't swap horizontal for vertical layout, or remove the icon.
- Don't use the primary color decoratively. Treat it as a functional accent.
