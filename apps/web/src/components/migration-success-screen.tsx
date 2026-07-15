import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  getMigrationStatus,
  startMigration,
  type MigrationOut,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MigrationRunBar } from "@/components/migration-run-bar";
import { PipelineCanvas } from "@/components/pipeline-canvas";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  stopped_early: "Stopped early",
};

const STATUS_VARIANTS: Record<string, "outline" | "pass" | "fail" | "neutral"> = {
  pending: "outline",
  running: "neutral",
  completed: "pass",
  failed: "fail",
  stopped_early: "neutral",
};

/**
 * Shown once a Migration exists for this pipeline — either just created by
 * `<NewMigrationWizard>` or (on a later visit to the Migrations tab)
 * discovered via `GET /pipelines/{id}/migrations`. Extracted unchanged from
 * the old `/pipelines/$pipelineId/migrations/new` route (see
 * DEV_TRACKER.md's "Phase 1 — Unified pipeline workspace") except:
 * `pipelineId` still arrives as a string prop (kept as-is — it's what
 * `<PipelineCanvas>`'s pid conversion and the old route's params both
 * already expected), `onBackToCanvas` replaces the old direct navigate call
 * so pipeline-workspace.tsx can decide that "back" means "switch tabs" not
 * "leave the page", and `started` now initializes from the migration's own
 * status (not always `false`) so a migration discovered already-running
 * shows its live run state immediately instead of the "not started" screen.
 */
export function MigrationSuccessScreen({
  migration,
  pipelineId,
  onBackToCanvas,
}: {
  migration: MigrationOut;
  pipelineId: string;
  onBackToCanvas: () => void;
}) {
  const pid = Number(pipelineId);
  const [started, setStarted] = useState(migration.status !== "pending");

  const startMutation = useMutation({
    mutationFn: () => startMigration(pid, migration.id),
    onSuccess: () => setStarted(true),
  });

  const statusQuery = useQuery({
    queryKey: ["migration-status", pid, migration.id],
    queryFn: () => getMigrationStatus(pid, migration.id),
    enabled: started,
    initialData: started ? migration : undefined,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "running" ? 2000 : false;
    },
  });

  const status = statusQuery.data;
  const isRunning = status?.status === "running";
  const isTerminal = status && ["completed", "failed", "stopped_early"].includes(status.status);

  return (
    <Card>
      <CardContent className="p-8">
        <div className="mb-4 flex items-center gap-2 text-14 font-medium text-ink">
          <span>Migration #{migration.id} created</span>
          <Badge variant={STATUS_VARIANTS[status?.status ?? "pending"]}>
            {STATUS_LABELS[status?.status ?? "pending"]}
          </Badge>
        </div>

        {!started && (
          <>
            <p className="mb-6 max-w-[640px] text-14 text-ink-soft">
              Migration saved. Make sure all rubrics are approved, then start the optimizer below.
            </p>
            {startMutation.isError && (
              <p className="mb-4 text-13 text-parity-fail" role="alert">
                {startMutation.error instanceof ApiError
                  ? startMutation.error.message
                  : "Failed to start migration."}
              </p>
            )}
            <div className="flex gap-3">
              <Button
                variant="primary"
                onClick={() => startMutation.mutate()}
                disabled={startMutation.isPending}
              >
                {startMutation.isPending ? "Starting…" : "Start migration"}
              </Button>
              <Button variant="secondary" onClick={onBackToCanvas}>
                Back to pipeline canvas
              </Button>
            </div>
          </>
        )}

        {started && (
          <div className="mt-2">
            <MigrationRunBar
              status={status}
              isConnecting={!isTerminal && !isRunning && statusQuery.isLoading}
            />

            {(isRunning || isTerminal) && (
              <div className="mt-4 h-[420px] overflow-hidden rounded-card border border-line">
                <PipelineCanvas
                  pipelineId={pid}
                  stageStates={status?.stage_states}
                  runningSubstep={status?.progress_substep}
                />
              </div>
            )}

            <div className="mt-6">
              <Button variant="secondary" onClick={onBackToCanvas}>
                Back to pipeline canvas
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
