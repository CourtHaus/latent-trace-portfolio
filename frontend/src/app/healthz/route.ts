import { NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL;

export async function GET() {
  if (!API_BASE_URL) {
    return NextResponse.json(
      { status: "error", reason: "API_BASE_URL missing" },
      { status: 503 },
    );
  }

  try {
    const res = await fetch(`${API_BASE_URL}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2_000),
    });
    if (!res.ok) {
      return NextResponse.json(
        { status: "error", reason: `api ${res.status}` },
        { status: 503 },
      );
    }
  } catch {
    return NextResponse.json(
      { status: "error", reason: "api unreachable" },
      { status: 503 },
    );
  }

  return NextResponse.json({ status: "ok" });
}
