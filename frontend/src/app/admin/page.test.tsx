import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { OperatorSnapshot } from "@/lib/operatorSnapshot";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((path: string) => {
    throw new Error(`redirect:${path}`);
  }),
}));

vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(),
}));

vi.mock("@/lib/operatorSnapshot", () => ({
  getOperatorSnapshot: vi.fn(),
}));

import { getOperatorSnapshot } from "@/lib/operatorSnapshot";
import { createClient } from "@/lib/supabase/server";
import AdminPage from "./page";

const snapshot: OperatorSnapshot = {
  system: {
    health: "healthy",
    generated_at: "2026-05-20T12:00:00Z",
    database_ok: true,
    environment: "production",
  },
  dataset: {
    version: "v2026.05",
    published_dataset_versions: 2,
    total_cases: 100,
    state_count: 5,
    source_count: 7,
    geocoded_cases: 95,
    geocoded_percent: 95,
    last_ingested_at: "2026-05-20T11:00:00Z",
    last_published_at: "2026-05-20T11:10:00Z",
  },
  pipeline: {
    ingestion: {
      queued: 0,
      running: 0,
      succeeded: 3,
      failed: 0,
      partial: 0,
      skipped: 0,
    },
    extraction: {
      queued: 0,
      running: 0,
      succeeded: 8,
      failed: 0,
      partial: 0,
      skipped: 0,
    },
    geocoding: {
      queued: 0,
      running: 0,
      succeeded: 9,
      failed: 0,
      partial: 0,
      skipped: 0,
    },
    stale_running_count: 0,
    old_queued_count: 0,
  },
  warnings: [],
  latest_failures: [],
  sources: [],
};

function mockAuth(opts: { user: object | null; accessToken: string | null }) {
  vi.mocked(createClient).mockResolvedValue({
    auth: {
      getUser: vi.fn().mockResolvedValue({ data: { user: opts.user } }),
      getSession: vi.fn().mockResolvedValue({
        data: {
          session: opts.accessToken ? { access_token: opts.accessToken } : null,
        },
      }),
    },
  } as never);
}

// A valid admin: getUser() confirms a real user and a token is available.
function mockSession(accessToken: string | null) {
  mockAuth({
    user: accessToken ? { id: "admin-user-id" } : null,
    accessToken,
  });
}

describe("/admin page", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("redirects unauthenticated users to login", async () => {
    mockSession(null);

    await expect(AdminPage()).rejects.toThrow("redirect:/admin/login");
  });

  it("redirects when a session cookie exists but getUser() rejects it (SEC-F02)", async () => {
    // Unverified cookie present (getSession has a token) but getUser() — which
    // revalidates against the auth server — returns no user. Must still redirect.
    mockAuth({ user: null, accessToken: "stale-cookie-token" });

    await expect(AdminPage()).rejects.toThrow("redirect:/admin/login");
    expect(getOperatorSnapshot).not.toHaveBeenCalled();
  });

  it("renders unauthorized message when API returns 403", async () => {
    mockSession("token");
    vi.mocked(getOperatorSnapshot).mockRejectedValue(
      new ApiError(403, "forbidden"),
    );

    const tree = await AdminPage();
    render(tree);

    expect(
      screen.getByRole("heading", { name: /admin access required/i }),
    ).toBeInTheDocument();
  });

  it("renders the ops snapshot for an authenticated admin", async () => {
    mockSession("token");
    vi.mocked(getOperatorSnapshot).mockResolvedValue(snapshot);

    const tree = await AdminPage();
    render(tree);

    expect(getOperatorSnapshot).toHaveBeenCalledWith("token");
    expect(
      screen.getByRole("heading", { name: /ops snapshot/i }),
    ).toBeInTheDocument();
  });
});
