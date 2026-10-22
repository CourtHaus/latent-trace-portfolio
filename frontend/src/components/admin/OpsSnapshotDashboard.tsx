import {
  AlertTriangle,
  CheckCircle2,
  Database,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type {
  OperatorSnapshot,
  OperatorStatusCounts,
} from "@/lib/operatorSnapshot";

function formatDate(value: string | null) {
  if (!value) {
    return "None";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

function formatHealth(value: OperatorSnapshot["system"]["health"]) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function HealthIcon({
  health,
}: {
  health: OperatorSnapshot["system"]["health"];
}) {
  if (health === "healthy") {
    return <CheckCircle2 aria-hidden="true" className="size-5 text-emerald-600" />;
  }

  if (health === "critical") {
    return <ShieldAlert aria-hidden="true" className="size-5 text-destructive" />;
  }

  return <AlertTriangle aria-hidden="true" className="size-5 text-amber-600" />;
}

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <Card size="sm">
      <CardContent className="p-4">
        <p className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
          {label}
        </p>
        <p className="mt-2 text-3xl font-medium tabular-nums tracking-normal">
          {value}
        </p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

function PipelineRow({
  label,
  counts,
}: {
  label: string;
  counts: OperatorStatusCounts;
}) {
  return (
    <tr className="border-b border-border last:border-b-0">
      <th className="py-2 pr-4 text-left font-medium">{label}</th>
      <td className="py-2 pr-4 text-right tabular-nums">{counts.queued}</td>
      <td className="py-2 pr-4 text-right tabular-nums">{counts.running}</td>
      <td className="py-2 pr-4 text-right tabular-nums">{counts.succeeded}</td>
      <td className="py-2 pr-4 text-right tabular-nums">{counts.failed}</td>
      <td className="py-2 text-right tabular-nums">
        {counts.partial + counts.skipped}
      </td>
    </tr>
  );
}

export function OpsSnapshotDashboard({
  snapshot,
}: {
  snapshot: OperatorSnapshot;
}) {
  return (
    <main className="px-5 py-8 sm:px-8 lg:px-10">
      <section className="mx-auto max-w-app space-y-6">
        <header className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
              Operator
            </p>
            <h1 className="text-3xl font-medium tracking-normal">
              Ops Snapshot
            </h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Generated {formatDate(snapshot.system.generated_at)} in{" "}
              {snapshot.system.environment}.
            </p>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {snapshot.dataset.version}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <a className={buttonVariants({ variant: "outline" })} href="/admin">
              <RefreshCw aria-hidden="true" />
              Refresh
            </a>
            <form action="/admin/logout" method="post">
              <Button type="submit" variant="ghost">
                Logout
              </Button>
            </form>
          </div>
        </header>

        <Card size="sm">
          <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <HealthIcon health={snapshot.system.health} />
              <div>
                <p className="font-medium">{formatHealth(snapshot.system.health)}</p>
                <p className="text-sm leading-6 text-muted-foreground">
                  Published dataset {snapshot.dataset.version}; database{" "}
                  {snapshot.system.database_ok ? "reachable" : "unreachable"}.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 text-sm leading-6 text-muted-foreground">
              <Database aria-hidden="true" className="size-4" />
              <span>Last published {formatDate(snapshot.dataset.last_published_at)}</span>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="Cases"
            value={snapshot.dataset.total_cases.toLocaleString()}
            detail={`${snapshot.dataset.published_dataset_versions} published dataset versions`}
          />
          <MetricCard
            label="States"
            value={snapshot.dataset.state_count.toLocaleString()}
            detail="Represented in published data"
          />
          <MetricCard
            label="Sources"
            value={snapshot.dataset.source_count.toLocaleString()}
            detail="Active published source systems"
          />
          <MetricCard
            label="Geocoded"
            value={formatPercent(snapshot.dataset.geocoded_percent)}
            detail={`${snapshot.dataset.geocoded_cases.toLocaleString()} cases with coordinates`}
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <Card size="sm">
            <CardContent className="p-4">
              <h2 className="mb-3 text-base font-medium">Warnings</h2>
              {snapshot.warnings.length === 0 ? (
                <p className="text-sm text-muted-foreground">No active warnings.</p>
              ) : (
                <ul className="space-y-3">
                  {snapshot.warnings.map((warning) => (
                    <li
                      key={warning.code}
                      className="rounded-md border border-border p-3"
                    >
                      <p className="text-sm font-medium">{warning.title}</p>
                      <p className="mt-1 text-sm leading-6 text-muted-foreground">
                        {warning.detail}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card size="sm">
            <CardContent className="p-4">
              <h2 className="mb-3 text-base font-medium">Pipeline</h2>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="border-b border-border text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-4 text-left font-medium">Queue</th>
                      <th className="py-2 pr-4 text-right font-medium">Queued</th>
                      <th className="py-2 pr-4 text-right font-medium">Running</th>
                      <th className="py-2 pr-4 text-right font-medium">Succeeded</th>
                      <th className="py-2 pr-4 text-right font-medium">Failed</th>
                      <th className="py-2 text-right font-medium">Other</th>
                    </tr>
                  </thead>
                  <tbody>
                    <PipelineRow label="Ingestion" counts={snapshot.pipeline.ingestion} />
                    <PipelineRow label="Extraction" counts={snapshot.pipeline.extraction} />
                    <PipelineRow label="Geocoding" counts={snapshot.pipeline.geocoding} />
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                {snapshot.pipeline.old_queued_count} old queued,{" "}
                {snapshot.pipeline.stale_running_count} stale running.
              </p>
            </CardContent>
          </Card>
        </div>

        <Card size="sm">
          <CardContent className="p-4">
            <h2 className="mb-3 text-base font-medium">Latest Failures</h2>
            {snapshot.latest_failures.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recent failed jobs.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-prose text-sm">
                  <thead className="border-b border-border text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-4 text-left font-medium">Type</th>
                      <th className="py-2 pr-4 text-left font-medium">Job</th>
                      <th className="py-2 pr-4 text-left font-medium">Source</th>
                      <th className="py-2 pr-4 text-left font-medium">Case</th>
                      <th className="py-2 text-left font-medium">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.latest_failures.map((failure) => (
                      <tr
                        key={`${failure.job_type}-${failure.job_id}`}
                        className="border-b border-border last:border-b-0"
                      >
                        <td className="py-2 pr-4 capitalize">
                          {failure.job_type}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs">
                          {failure.job_id}
                        </td>
                        <td className="py-2 pr-4">
                          {failure.source_code ?? "None"}
                        </td>
                        <td className="py-2 pr-4">
                          {failure.case_name ??
                            (failure.case_id ? `#${failure.case_id}` : "None")}
                        </td>
                        <td className="max-w-[420px] py-2 leading-6">
                          {failure.error_detail ?? "No error detail"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card size="sm">
          <CardContent className="p-4">
            <h2 className="mb-3 text-base font-medium">Sources</h2>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {snapshot.sources.map((source) => (
                <div
                  key={source.code}
                  className="rounded-md border border-border p-3 text-sm"
                >
                  <p className="font-medium">{source.name}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <div>
                      <p className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                        Cases
                      </p>
                      <p className="tabular-nums">
                        {source.case_count.toLocaleString()}
                      </p>
                    </div>
                    <div>
                      <p className="font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
                        Geocoded
                      </p>
                      <p className="tabular-nums">
                        {formatPercent(source.geocoded_percent)}
                      </p>
                    </div>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    {source.state ?? "No state"} - {source.year_min ?? "?"} to{" "}
                    {source.year_max ?? "?"}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </section>
    </main>
  );
}
