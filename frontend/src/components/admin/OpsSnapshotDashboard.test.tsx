import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OperatorSnapshot } from "@/lib/operatorSnapshot";
import { OpsSnapshotDashboard } from "./OpsSnapshotDashboard";

const snapshot: OperatorSnapshot = {
  system: {
    health: "warning",
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
      queued: 1,
      running: 0,
      succeeded: 3,
      failed: 1,
      partial: 0,
      skipped: 0,
    },
    extraction: {
      queued: 2,
      running: 1,
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
    old_queued_count: 1,
  },
  warnings: [
    {
      severity: "warning",
      code: "recent_failed_jobs",
      title: "Recent failed jobs",
      detail: "1 failed job or run records need review.",
    },
  ],
  latest_failures: [
    {
      job_type: "ingestion",
      job_id: "7",
      status: "failed",
      source_code: "VSPCCD_VA",
      case_id: null,
      case_name: null,
      error_detail: "boom",
      created_at: "2026-05-20T10:00:00Z",
      started_at: null,
      completed_at: null,
    },
  ],
  sources: [
    {
      code: "VSPCCD_VA",
      name: "Virginia State Police",
      state: "VA",
      case_count: 90,
      geocoded_count: 90,
      geocoded_percent: 100,
      year_min: 1961,
      year_max: 2024,
    },
  ],
};

describe("OpsSnapshotDashboard", () => {
  it("renders top-level health and dataset metrics", () => {
    render(<OpsSnapshotDashboard snapshot={snapshot} />);

    expect(
      screen.getByRole("heading", { name: /ops snapshot/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("v2026.05")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("95.0%")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
  });

  it("renders warnings and latest failures", () => {
    render(<OpsSnapshotDashboard snapshot={snapshot} />);

    expect(screen.getByText("Recent failed jobs")).toBeInTheDocument();
    expect(screen.getByText("VSPCCD_VA")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("renders source quality summary", () => {
    render(<OpsSnapshotDashboard snapshot={snapshot} />);

    expect(screen.getByText("Virginia State Police")).toBeInTheDocument();
    expect(screen.getByText("100.0%")).toBeInTheDocument();
  });
});
