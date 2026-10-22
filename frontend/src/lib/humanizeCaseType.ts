/**
 * Render a raw case_type DB value as a human-readable label.
 *
 * Known values are hard-coded; unknown values get a generic
 * snake_case → Title Case fallback so a new state's value doesn't
 * silently render as e.g. "foo_bar".
 */
const KNOWN: Readonly<Record<string, string>> = {
  homicide: "Homicide",
  suspicious_death: "Suspicious Death",
};

export function humanizeCaseType(raw: string): string {
  if (!raw) return "";
  const known = KNOWN[raw];
  if (known) return known;
  return raw
    .split("_")
    .map((w) => (w.length > 0 ? w[0]!.toUpperCase() + w.slice(1) : ""))
    .join(" ");
}
