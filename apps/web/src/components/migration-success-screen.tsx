import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  getMigrationResults,
  getMigrationStatus,
  getPipelineDag,
  startMigration,
  type ActivityLogEntry,
  type MigrationOut,
  type StageResultOut,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  DrawerRoot,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from "@/components/ui/drawer";
import { MigrationRunBar } from "@/components/migration-run-bar";
import { PipelineCanvas } from "@/components/pipeline-canvas";
import { SUBSTEP_LABEL } from "@/components/stage-node";
import { diffWords } from "@/lib/text-diff";

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
  // Set only when a *running* stage node is clicked (see onNodeClick below)
  // — the reasoning drawer only ever has something live to show for the
  // one stage currently in progress.
  const [reasoningStageId, setReasoningStageId] = useState<number | null>(null);

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

  // Same queryKey PipelineCanvas itself uses for this pipeline's DAG - reads
  // from the shared React Query cache (no extra fetch) once PipelineCanvas
  // below has loaded it. Only used here for human-readable stage names in
  // the activity log / reasoning drawer.
  const dagQuery = useQuery({
    queryKey: ["pipeline-dag", pid],
    queryFn: () => getPipelineDag(pid),
    enabled: started,
  });

  function stageName(stageId: number): string {
    return dagQuery.data?.stages[String(stageId)]?.name ?? `Stage ${stageId}`;
  }

  const status = statusQuery.data;
  const isRunning = status?.status === "running";
  const isTerminal = status && ["completed", "failed", "stopped_early"].includes(status.status);

  // Results (before/after prompt diff) only becomes meaningful once the run
  // has actually produced winning candidates — fetched once the migration
  // reaches a terminal state. The endpoint itself doesn't error before
  // then either (see migrations.py's get_migration_results docstring), but
  // there's nothing worth showing/polling for while still running.
  const resultsQuery = useQuery({
    queryKey: ["migration-results", pid, migration.id],
    queryFn: () => getMigrationResults(pid, migration.id),
    enabled: Boolean(isTerminal),
  });

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
                  onNodeClick={(stageId) => {
                    // Only a *running* node has a live reasoning feed to
                    // show - clicking a done/idle/failed node is a no-op
                    // here (unlike the static Canvas tab's rubric drawer).
                    if (status?.stage_states?.[String(stageId)] === "running") {
                      setReasoningStageId(stageId);
                    }
                  }}
                />
              </div>
            )}

            {(isRunning || isTerminal) && (
              <ActivityLogList entries={status?.activity_log ?? null} stageName={stageName} />
            )}

            {isTerminal && (
              <StageResultsSection
                results={resultsQuery.data}
                isLoading={resultsQuery.isLoading}
              />
            )}

            <div className="mt-6">
              <Button variant="secondary" onClick={onBackToCanvas}>
                Back to pipeline canvas
              </Button>
            </div>
          </div>
        )}
      </CardContent>

      <StageReasoningDrawer
        stageId={reasoningStageId}
        stageName={reasoningStageId !== null ? stageName(reasoningStageId) : ""}
        entries={status?.activity_log ?? null}
        onClose={() => setReasoningStageId(null)}
      />
    </Card>
  );
}

/** One human-readable line for an activity log entry — the real critique
 * text/judge summary when the phase carried one (see StagePhaseEvent's
 * docstring in packages/core), otherwise the same human-readable phase
 * label stage-node.tsx's substep line already uses. Never the raw phase
 * enum value on its own. */
function activityLineText(entry: ActivityLogEntry): string {
  return entry.detail ?? SUBSTEP_LABEL[entry.phase];
}

/**
 * Chronological activity log for the whole run, alongside the live DAG —
 * every on_phase event across every stage, not just the one currently
 * selected in the reasoning drawer. Newest at the bottom (log/chat
 * convention) and auto-scrolls as new entries arrive via the existing
 * 2s status poll — no new polling mechanism introduced.
 */
function ActivityLogList({
  entries,
  stageName,
}: {
  entries: ActivityLogEntry[] | null;
  stageName: (stageId: number) => string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  if (!entries || entries.length === 0) return null;

  return (
    <div className="mt-4 rounded-card border border-line">
      <p className="border-b border-line px-4 py-2 text-12 font-medium text-ink-soft">
        Activity log
      </p>
      <div ref={scrollRef} className="max-h-[200px] space-y-1 overflow-y-auto p-4" role="log">
        {entries.map((entry, i) => (
          <p key={i} className="font-mono text-12 text-ink-soft">
            <span className="text-ink">{stageName(entry.stage_id)}</span>: {activityLineText(entry)}
          </p>
        ))}
      </div>
    </div>
  );
}

/**
 * Results section (Phase C — before/after prompt diff): once a migration
 * reaches a terminal state, shows every stage's original prompt
 * (`Stage.prompt_template`) against the winning candidate's prompt side by
 * side as a unified word diff, plus which target model won and its
 * composite score. Read-only, display-only — no new optimizer/scoring
 * logic, just rendering what `GET .../results` already computed (see
 * migrations.py's `get_migration_results`).
 *
 * A stage with no `Candidate` rows yet (e.g. it never got a chance to run
 * before a `failed`/`stopped_early` stop) simply doesn't appear in
 * `results` — same "only what's available" contract as the endpoint.
 */
function StageResultsSection({
  results,
  isLoading,
}: {
  results: StageResultOut[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="mt-6">
        <p className="text-13 text-ink-soft">Loading results…</p>
      </div>
    );
  }

  if (!results || results.length === 0) {
    return (
      <div className="mt-6">
        <p className="text-13 text-ink-soft">
          No winning candidates were recorded for any stage yet.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-6">
      <p className="mb-2 text-12 font-medium text-ink-soft">
        Results — before / after prompts
      </p>
      <div className="space-y-3">
        {results.map((result) => (
          <StageResultCard key={result.stage_id} result={result} />
        ))}
      </div>
    </div>
  );
}

function StageResultCard({ result }: { result: StageResultOut }) {
  const ops = diffWords(result.original_prompt, result.winning_prompt);

  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-13 font-medium text-ink">{result.stage_name}</span>
          <span className="text-12 text-ink-soft">
            {result.winning_model} · score {result.score.toFixed(2)}
          </span>
        </div>
        <pre className="whitespace-pre-wrap rounded-control border border-line bg-paper p-3 font-mono text-12 leading-normal text-ink">
          {ops.map((op, i) => {
            if (op.type === "delete") {
              return (
                <span key={i} className="bg-parity-fail/10 text-parity-fail line-through">
                  {op.text}
                </span>
              );
            }
            if (op.type === "insert") {
              return (
                <span key={i} className="bg-parity-pass/10 text-parity-pass">
                  {op.text}
                </span>
              );
            }
            return <span key={i}>{op.text}</span>;
          })}
        </pre>
      </CardContent>
    </Card>
  );
}

/**
 * Live reasoning feed (Phase B) — clicking a *running* stage node on the
 * live DAG opens this, showing the latest real LLM reasoning text
 * (critique text / judge-reasoning summary) captured for that stage so
 * far, filtered from the same activity log. Reuses the Drawer primitives
 * StageRubricDrawer (pipeline-workspace.tsx) already established for
 * stage-scoped side panels, rather than introducing a new panel component.
 */
function StageReasoningDrawer({
  stageId,
  stageName,
  entries,
  onClose,
}: {
  stageId: number | null;
  stageName: string;
  entries: ActivityLogEntry[] | null;
  onClose: () => void;
}) {
  const stageEntries = (entries ?? []).filter((e) => e.stage_id === stageId);
  const latest = stageEntries[stageEntries.length - 1];

  return (
    <DrawerRoot open={stageId !== null} onOpenChange={(open) => !open && onClose()}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>{stageName || "Stage reasoning"}</DrawerTitle>
          <DrawerDescription>Live optimizer reasoning for this stage</DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          {!latest && (
            <p className="text-13 text-ink-soft">
              No reasoning captured for this stage yet — check back in a moment.
            </p>
          )}
          {latest && (
            <div className="space-y-4">
              <div>
                <h3 className="mb-1 text-12 font-medium text-ink">
                  {SUBSTEP_LABEL[latest.phase]}
                </h3>
                <p className="whitespace-pre-wrap text-13 text-ink">{activityLineText(latest)}</p>
              </div>

              {stageEntries.length > 1 && (
                <div>
                  <h3 className="mb-1 text-12 font-medium text-ink">Earlier this run</h3>
                  <ul className="space-y-1">
                    {stageEntries
                      .slice(0, -1)
                      .reverse()
                      .map((entry, i) => (
                        <li key={i} className="text-13 text-ink-soft">
                          {SUBSTEP_LABEL[entry.phase]}
                          {entry.detail ? `: ${entry.detail}` : ""}
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </DrawerBody>
      </DrawerContent>
    </DrawerRoot>
  );
}
