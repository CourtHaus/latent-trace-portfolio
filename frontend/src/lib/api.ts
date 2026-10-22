import "server-only";

type ApiFetchOptions = RequestInit & {
  next?: { revalidate?: number | false; tags?: string[] };
};

/**
 * Default revalidate window (seconds) for read-only GET helpers. Cold-case
 * data only changes on rare, user-driven ingest, so a long window keeps the
 * Vercel Data Cache absorbing spikes with effectively zero practical staleness.
 * 1h fresh; the API's matching `stale-while-revalidate=86400` covers the rest.
 */
export const READ_REVALIDATE_SECONDS = 3600;

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init?: ApiFetchOptions,
): Promise<T> {
  const API_BASE_URL = process.env.API_BASE_URL;
  if (!API_BASE_URL) {
    throw new Error("API_BASE_URL must be set (see .env.local.example)");
  }

  // 30s default accommodates Cloud Run cold starts when `--min-instances=0`
  // (current self-funded preview config). If you switch to `--min-instances=1`
  // (no cold starts, but always-on billing), lower this — 8-10s is plenty for
  // a hot API. Override per-call via `init.signal = AbortSignal.timeout(N)`.
  const signal = init?.signal ?? AbortSignal.timeout(30_000);

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal,
      // Opt-in caching: when a caller passes `next` (revalidate), let Next.js
      // own caching. Everything else (writes, admin) stays uncached.
      cache: init?.cache ?? (init?.next ? undefined : "no-store"),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new Error(
        `apiFetch failed: ${init?.method ?? "GET"} ${path} -> timed out`,
      );
    }
    throw err;
  }

  if (!res.ok) {
    if (process.env.NODE_ENV !== "production") {
      const bodyPreview = (await res.clone().text().catch(() => "")).slice(0, 500);
      throw new ApiError(
        res.status,
        `apiFetch failed: ${init?.method ?? "GET"} ${path} -> ${res.status} ${res.statusText}\n${bodyPreview}`,
      );
    }
    throw new ApiError(
      res.status,
      `apiFetch failed: ${init?.method ?? "GET"} ${path} -> ${res.status}`,
    );
  }

  return (await res.json()) as T;
}
