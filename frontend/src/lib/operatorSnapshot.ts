import "server-only";

import { apiFetch } from "./api";

export type HealthStatus = "healthy" | "warning" | "critical";
export type WarningSeverity = "info" | "warning" | "critical";
export type JobType = "ingestion" | "extraction" | "geocoding";

export interface OperatorStatusCounts {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  partial: number;
  skipped: number;
}

export interface OperatorSnapshot {
  system: {
    health: HealthStatus;
    generated_at: string;
    database_ok: boolean;
    environment: string;
  };
  dataset: {
    version: string;
    published_dataset_versions: number;
    total_cases: number;
    state_count: number;
    source_count: number;
    geocoded_cases: number;
    geocoded_percent: number;
    last_ingested_at: string | null;
    last_published_at: string | null;
  };
  pipeline: {
    ingestion: OperatorStatusCounts;
    extraction: OperatorStatusCounts;
    geocoding: OperatorStatusCounts;
    stale_running_count: number;
    old_queued_count: number;
  };
  warnings: Array<{
    severity: WarningSeverity;
    code: string;
    title: string;
    detail: string;
  }>;
  latest_failures: Array<{
    job_type: JobType;
    job_id: string;
    status: string;
    source_code: string | null;
    case_id: number | null;
    case_name: string | null;
    error_detail: string | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
  }>;
  sources: Array<{
    code: string;
    name: string;
    state: string | null;
    case_count: number;
    geocoded_count: number;
    geocoded_percent: number;
    year_min: number | null;
    year_max: number | null;
  }>;
}

export async function getOperatorSnapshot(
  accessToken: string,
): Promise<OperatorSnapshot> {
  return apiFetch<OperatorSnapshot>("/api/v1/operator/snapshot", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
