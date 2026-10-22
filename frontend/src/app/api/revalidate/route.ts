import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";

/**
 * On-demand cache invalidation, called by scripts/sync_to_supabase.sh after an
 * ingest sync so freshly-synced data appears on the public site immediately
 * instead of waiting out the 1h Data Cache window.
 *
 * POST with header `x-revalidate-secret: $REVALIDATE_SECRET`. Revalidates every
 * route under the root layout, purging the cached renders and their fetched data.
 */
export async function POST(request: Request): Promise<NextResponse> {
  const secret = process.env.REVALIDATE_SECRET;
  if (!secret) {
    return NextResponse.json(
      { revalidated: false, reason: "REVALIDATE_SECRET not configured" },
      { status: 503 },
    );
  }
  if (request.headers.get("x-revalidate-secret") !== secret) {
    return NextResponse.json(
      { revalidated: false, reason: "unauthorized" },
      { status: 401 },
    );
  }

  revalidatePath("/", "layout");
  return NextResponse.json({ revalidated: true, scope: "/" });
}
