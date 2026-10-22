/**
 * Map a stored victim gender to a display label. The API normalizes gender to
 * {M, F, unknown}; some sources store full words. Values may be source-provided
 * or Tier-2 narrative extractions (marked by gender_source='tier2' with a
 * reveal-source affordance); race is never inferred. Returns null for null so
 * callers can render a placeholder; unrecognized values pass through unchanged.
 */
export function humanizeGender(gender: string | null): string | null {
  if (gender == null) return null;
  switch (gender.trim().toLowerCase()) {
    case "m":
    case "male":
      return "Male";
    case "f":
    case "female":
      return "Female";
    case "unknown":
      return "Unknown";
    default:
      return gender;
  }
}
