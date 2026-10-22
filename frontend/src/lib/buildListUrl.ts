/**
 * Build a /cold-cases URL with the current searchParams plus overrides.
 *
 * Source params come from Next's searchParams shape (string | string[] | undefined).
 * Overrides are explicit key -> (string | number | null). null removes the key.
 *
 * Used by the pagination component to produce hrefs that preserve active filters
 * while flipping the page param — preventing pagination clicks from silently
 * dropping the user's filter state.
 */
export function buildListUrl(
  source: Record<string, string | string[] | undefined>,
  overrides: Record<string, string | number | null>,
): string {
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(source)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const v of value) {
        if (v !== "") params.append(key, v);
      }
    } else if (value !== "") {
      params.append(key, value);
    }
  }

  for (const [key, value] of Object.entries(overrides)) {
    params.delete(key);
    if (value !== null) {
      params.append(key, String(value));
    }
  }

  const qs = params.toString();
  return qs ? `/cold-cases?${qs}` : "/cold-cases";
}
