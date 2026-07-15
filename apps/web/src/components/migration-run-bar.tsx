import type { MigrationOut } from "@/lib/api";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  stopped_early: "Stopped early",
};

export interface MigrationRunBarProps {
  status: MigrationOut | undefined;
  isConnecting: boolean;
}

/**
 * Slim run-bar shown above the DAG canvas while a migration is running or
 * has just finished — progress ("N of M" + bar), cost-so-far, and the
 * stop reason for a failed/stopped-early run. Polled by the caller (see
 * `MigrationSuccessScreen` in routes/new-migration.tsx) via
 * `refetchInterval` on `GET .../status`; this component is pure display.
 */
export function MigrationRunBar({ status, isConnecting }: MigrationRunBarProps) {
  const isRunning = status?.status === "running";
  const isTerminal = status != null && ["completed", "failed", "stopped_early"].includes(status.status);
  const progressPercent =
    status?.progress_current != null && status?.progress_total != null && status.progress_total > 0
      ? Math.round((status.progress_current / status.progress_total) * 100)
      : null;

  if (isConnecting && !status) {
    return <p className="text-13 text-ink-soft">Connecting…</p>;
  }

  return (
    <div className="rounded-card border border-line bg-paper p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-2">
          <span
            role="img"
            aria-label={isRunning ? "Migration running" : STATUS_LABELS[status?.status ?? "pending"]}
            className={
              "h-2 w-2 shrink-0 rounded-full " +
              (isRunning
                ? "animate-pulse bg-beam"
                : status?.status === "completed"
                  ? "bg-parity-pass"
                  : status?.status === "failed"
                    ? "bg-parity-fail"
                    : status?.status === "stopped_early"
                      ? "bg-parity-near"
                      : "bg-ink-soft/40")
            }
          />
          <span className="truncate text-13 font-medium text-ink">
            {isRunning
              ? status?.progress_stage_name
                ? `Optimizing: ${status.progress_stage_name}`
                : "Starting optimizer…"
              : STATUS_LABELS[status?.status ?? "pending"]}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-4 text-13 tabular-nums text-ink-soft">
          {progressPercent !== null && (
            <span>
              {status?.progress_current} / {status?.progress_total} stages
            </span>
          )}
          {status?.total_cost_usd != null && (
            <span>
              Cost so far: <span className="font-mono text-ink">${status.total_cost_usd.toFixed(4)}</span>
            </span>
          )}
        </div>
      </div>

      {isRunning && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-line">
          <div
            className="h-full rounded-full bg-beam transition-all duration-700 ease-out"
            style={{ width: `${progressPercent ?? 0}%` }}
          />
        </div>
      )}

      {isTerminal && (status.status === "failed" || status.status === "stopped_early") && status.stop_reason && (
        <p className="mt-2 text-13 text-parity-fail">{status.stop_reason}</p>
      )}
    </div>
  );
}
