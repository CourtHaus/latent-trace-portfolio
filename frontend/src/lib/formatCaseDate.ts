/**
 * Format a cold-case incident date for display.
 *
 * Sources hand us ISO-ish strings of varying completeness; some carry only a
 * year, and many are null. We never want a raw "1998-05-14" in the UI.
 *   "1998-05-14"           -> "May 14, 1998"
 *   "1998-05-14T00:00:00Z" -> "May 14, 1998"
 *   "1998-00-00" / "1998"  -> "1998"
 *   null / "" / "  "       -> "—"
 *   "circa 1990s"          -> "circa 1990s"   (unparseable: pass through)
 */
export function formatCaseDate(value: string | null | undefined): string {
  const trimmed = value?.trim();
  if (!trimmed) return "—";

  const ymd = /^(\d{4})-(\d{2})-(\d{2})/.exec(trimmed);
  if (!ymd) {
    const yearOnly = /^(\d{4})$/.exec(trimmed);
    return yearOnly?.[1] ?? trimmed;
  }

  const [, year = "", month = "", day = ""] = ymd;
  if (month === "00" || day === "00") return year;

  // Parse as UTC so the calendar day never shifts with the runner/browser TZ.
  const date = new Date(`${year}-${month}-${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return year;

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}
