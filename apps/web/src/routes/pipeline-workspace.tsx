import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import {
  approveRubric,
  importIntoExistingPipeline,
  listMigrations,
  listPipelines,
  listRubrics,
  updatePipeline,
  ApiError,
  type ImportResult,
  type MigrationOut,
  type PipelineSummary,
  type RubricOut,
} from "@/lib/api";
import { useMigrationStatusPoll } from "@/hooks/use-migration-status-poll";
import {
  describeDeterministicCheck,
  describeJudgeCriterion,
  type DeterministicCheckLike,
  type JudgeCriterionLike,
} from "@/lib/rubric-format";
import { AppShell } from "@/components/app-shell";
import { Dropzone } from "@/components/dropzone";
import { PipelineCanvas } from "@/components/pipeline-canvas";
import { DataTable } from "@/components/data-table";
import { RubricReviewPanel } from "@/components/rubric-review-panel";
import { ContractReviewPanel } from "@/components/contract-review-panel";
import { NewMigrationWizard } from "@/components/new-migration-wizard";
import { MigrationSuccessScreen } from "@/components/migration-success-screen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  DrawerRoot,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from "@/components/ui/drawer";
import { cn } from "@/lib/utils";

export type WorkspaceTab = "canvas" | "data" | "rubrics" | "contracts" | "migrations";

export const WORKSPACE_TABS: readonly WorkspaceTab[] = ["canvas", "data", "rubrics", "contracts", "migrations"];

const TAB_LABELS: Record<WorkspaceTab, string> = {
  canvas: "Canvas",
  data: "Data",
  rubrics: "Rubrics",
  contracts: "Contracts",
  migrations: "Migrations",
};

/**
 * The unified pipeline workspace: one route (`/pipelines/$pipelineId`) with
 * a persistent header + tab bar, replacing the three previously-separate
 * screens (canvas, rubric review, migration wizard) — see DEV_TRACKER.md's
 * "Phase 1 — Unified pipeline workspace". Tab state lives in the URL's
 * `tab` search param (see router.tsx's `validateSearch`), so switching tabs
 * is a normal navigation (back/forward and bookmarking both work) rather
 * than local-only component state.
 */
export default function PipelineWorkspace() {
  const { pipelineId } = useParams({ from: "/pipelines/$pipelineId" });
  const { tab } = useSearch({ from: "/pipelines/$pipelineId" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pid = Number(pipelineId);

  const [selectedStageId, setSelectedStageId] = useState<number | null>(null);
  const [isEditingName, setIsEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [isImportRunOpen, setIsImportRunOpen] = useState(false);

  // No single GET /pipelines/{id} endpoint exists (only the list and /dag) -
  // reuse the list the home screen already fetches rather than adding one.
  const pipelinesQuery = useQuery({ queryKey: ["pipelines"], queryFn: listPipelines });
  const pipeline = pipelinesQuery.data?.find((p) => p.id === pid);

  // Same queryKey MigrationsTab uses below, so this shares its cache - no
  // second network round trip. Read here only to know whether the
  // "Migrations" tab needs a louder entry point: with no Migration yet, the
  // tab was previously a plain label identical in weight to Canvas/Data/
  // Rubrics, easy to read as passive navigation rather than "click here to
  // add the models you want to test" - see DEV_TRACKER.md's "Migration
  // wizard discoverability" note.
  const migrationsQuery = useQuery({ queryKey: ["migrations", pid], queryFn: () => listMigrations(pid) });
  const hasNoMigrationYet = migrationsQuery.data?.length === 0;

  const renameMutation = useMutation({
    mutationFn: (name: string) => updatePipeline(pid, { name }),
    onSuccess: (updated) => {
      queryClient.setQueryData<PipelineSummary[]>(["pipelines"], (old) =>
        old ? old.map((p) => (p.id === updated.id ? updated : p)) : old
      );
      setIsEditingName(false);
    },
  });

  function startEditingName() {
    setNameDraft(pipeline?.name ?? "");
    setIsEditingName(true);
  }

  function saveName() {
    const trimmed = nameDraft.trim();
    if (!trimmed || trimmed === pipeline?.name) {
      setIsEditingName(false);
      return;
    }
    renameMutation.mutate(trimmed);
  }

  function goToTab(nextTab: WorkspaceTab) {
    navigate({ to: "/pipelines/$pipelineId", params: { pipelineId }, search: { tab: nextTab } });
  }

  return (
    <AppShell>
      {/* h-full, not min-h - AppShell's <main> wrapper ("mx-auto
          max-w-[1440px]") now gives this a definite height (100% of the
          viewport space below the theme toggle bar - see app-shell.tsx),
          so only an explicit (not min-) height here is a "definite size"
          per the flexbox spec for percentage/flex-basis resolution to
          propagate down through the Canvas tab's nested flex-item chain to
          react-flow's own height:100% root - min-height alone produced a
          real pixel value at each layer but never a spec-definite one, so
          react-flow's DAG silently rendered in a 0-height viewport (see the
          Canvas tab wrapper below for the fuller trace). This used to be a
          hardcoded h-[calc(100vh-1px)], which assumed this div got the
          *entire* viewport height - true before the theme toggle bar
          existed as its own reserved row above it, and off by exactly that
          row's height afterwards, which is what re-introduced a page-level
          scrollbar on Canvas (React Flow's own pan/zoom, not page scroll,
          is supposed to be the only way to navigate a large DAG). */}
      <div className="flex h-full flex-col">
        <div className="border-b border-line px-8 py-4">
          <Link
            to="/pipelines"
            className="mb-2 inline-flex items-center gap-1 text-12 font-medium text-ink-soft hover:text-ink"
          >
            <ArrowLeft className="h-3 w-3" aria-hidden="true" />
            Pipelines
          </Link>
          <div className="flex items-start justify-between gap-4">
          {isEditingName ? (
            <div className="flex items-center gap-2">
              <Input
                autoFocus
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveName();
                  if (e.key === "Escape") setIsEditingName(false);
                }}
                onBlur={saveName}
                aria-label="Pipeline name"
                className="max-w-sm font-display text-20 font-semibold"
              />
              {renameMutation.isError && (
                <p className="text-12 text-parity-fail" role="alert">
                  Couldn't save name
                </p>
              )}
            </div>
          ) : (
            <button
              type="button"
              onClick={startEditingName}
              className="rounded-control text-left font-display text-28 font-semibold leading-display text-ink hover:bg-beam-soft/40"
              title="Click to rename"
            >
              {pipeline?.name ?? `Pipeline ${pipelineId}`}
            </button>
          )}

          <Button variant="secondary" onClick={() => setIsImportRunOpen(true)}>
            Import new run
          </Button>
          </div>

          <nav className="mt-4 flex gap-1" aria-label="Pipeline workspace tabs">
            {WORKSPACE_TABS.map((t) => {
              // While no Migration exists yet for this pipeline and we're not
              // already on that tab, render it as an obvious primary-styled
              // call-to-action ("+ Start a migration") instead of a plain tab
              // label - once a Migration exists (or the user is on the tab
              // itself), it goes back to behaving like every other tab.
              const isMigrationsCta = t === "migrations" && hasNoMigrationYet && tab !== "migrations";
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => goToTab(t)}
                  aria-current={tab === t ? "page" : undefined}
                  className={cn(
                    "rounded-control px-3 py-1.5 text-13 font-medium transition-colors duration-fast ease-out",
                    tab === t
                      ? "bg-beam-soft text-beam"
                      : isMigrationsCta
                        ? "bg-beam text-paper hover:brightness-110"
                        : "text-ink-soft hover:bg-beam-soft/50 hover:text-ink"
                  )}
                >
                  {isMigrationsCta ? "+ Start a migration" : TAB_LABELS[t]}
                </button>
              );
            })}
          </nav>
        </div>

        {/* flex + flex-col (not just the flex-1 item class) so the Canvas
            tab's PipelineCanvas - whose default wrapper div is itself
            "h-full min-h-[480px] flex-1" - gets a real flex-item main size
            to grow into. Without display:flex here, that inner flex-1 is
            inert (this div isn't a flex *container*), height:100% has no
            definite ancestor height to resolve against (min-height doesn't
            count per spec), and react-flow's own 100%-height root collapses
            to 0 - the DAG's nodes render in the DOM (data/labels are all
            present) but paint in a zero-height viewport, i.e. invisible.
            Single child per tab (mutually exclusive conditionals below) so
            this doesn't change layout for Data/Rubrics/Migrations.

            overflow-y-auto only for non-Canvas tabs: Canvas's own
            PipelineCanvas keeps a min-h-[480px] floor (guards against
            react-flow measuring a near-zero height during the same
            definite-size propagation this comment describes above), which
            can be a few pixels taller than the *actual* available space on
            a short-but-not-tiny window (confirmed: 480px vs 462px
            available in one real repro) - on the Canvas tab specifically
            that must never produce a scrollbar here (React Flow's own
            pan/zoom is the only way this content is meant to be reachable,
            same reasoning as app-shell.tsx's overflow-x-hidden), so it's
            overflow-hidden instead; the sub-480px sliver is simply
            clipped, never scrolled to. Every other tab's content can
            genuinely be taller than the viewport and still wants to
            scroll here as before. */}
        <div className={cn("flex flex-1 flex-col", tab === "canvas" ? "overflow-hidden" : "overflow-y-auto")}>
          {tab === "canvas" && (
            <CanvasTabContent
              pipelineId={pid}
              onNodeClick={(stageId) => setSelectedStageId(stageId)}
              onJumpToMigrations={() => goToTab("migrations")}
            />
          )}
          {tab === "data" && <DataTable pipelineId={pid} />}
          {tab === "rubrics" && (
            <div className="p-8">
              <RubricReviewPanel pipelineId={pid} />
            </div>
          )}
          {tab === "contracts" && (
            <div className="p-8">
              <ContractReviewPanel pipelineId={pid} />
            </div>
          )}
          {tab === "migrations" && (
            <div className="p-8">
              <MigrationsTab pipelineId={pid} onBackToCanvas={() => goToTab("canvas")} />
            </div>
          )}
        </div>
      </div>

      <StageRubricDrawer
        pipelineId={pid}
        stageId={selectedStageId}
        onClose={() => setSelectedStageId(null)}
        onViewFullRubric={(stageId) => {
          setSelectedStageId(null);
          window.location.hash = `rubric-${stageId}`;
          goToTab("rubrics");
        }}
      />

      <ImportRunDrawer
        pipelineId={pid}
        open={isImportRunOpen}
        onClose={() => setIsImportRunOpen(false)}
      />
    </AppShell>
  );
}

// Lighter cadence than the 2s live-status poll below — this one only exists
// to notice a migration starting/finishing while a user is parked on the
// Canvas tab, not to drive per-stage coloring itself.
const MIGRATION_LIST_POLL_INTERVAL_MS = 5000;

/**
 * Canvas tab's live-migration overlay. Product owner complaint this
 * addresses: "the canvas is static, it should be dynamic ... reflect what
 * is going on when the pipeline is running" — previously only the
 * Migrations tab's own embedded `<PipelineCanvas>` (in
 * `MigrationSuccessScreen`) ever received `stageStates`/`runningSubstep`;
 * the Canvas tab always rendered the same static, uncolored DAG regardless
 * of a migration running in the background. See DEV_TRACKER.md's "Canvas
 * tab live migration overlay" for the full design.
 *
 * Mounted only while the Canvas tab itself is active — a direct consequence
 * of the `{tab === "canvas" && (...)}` conditional in `PipelineWorkspace`
 * above — so both polls below exist only for as long as a user is actually
 * looking at this tab, never in the background on another tab. Two tiers,
 * not one:
 * - `listMigrations` at a lighter 5s cadence, just to notice a migration
 *   starting/finishing while parked here. Reuses the exact same
 *   `["migrations", pipelineId]` query key `MigrationsTab` below already
 *   uses, so switching to/from the Migrations tab is a cache hit, not a
 *   second fetch, in the common case.
 * - Once a running migration is found, `useMigrationStatusPoll` (shared
 *   with `MigrationSuccessScreen`'s own run view, see
 *   `hooks/use-migration-status-poll.ts`) takes over with the real 2s
 *   live-coloring poll — same queryKey/refetchInterval convention, so the
 *   two "poll a migration's stage_states" call sites can't drift apart.
 *
 * When nothing is running, this renders no `stageStates`/`runningSubstep`
 * props and no badge (and, since `useMigrationStatusPoll` is disabled
 * whenever `runningMigration` is `null`, no status poll at all — no polling
 * overhead beyond the lightweight 5s list check). `migrationRunning` below
 * is also handed straight to `<PipelineCanvas>`, which uses it to
 * auto-select its own Live/Analytics mode (Live while running, Analytics
 * otherwise — see DEV_TRACKER.md's Canvas/Graph merge entry, which folded
 * the former separate Graph tab's model/call drilldown view into this same
 * canvas as that Analytics mode).
 */
function CanvasTabContent({
  pipelineId,
  onNodeClick,
  onJumpToMigrations,
}: {
  pipelineId: number;
  onNodeClick: (stageId: number) => void;
  onJumpToMigrations: () => void;
}) {
  const migrationsQuery = useQuery({
    queryKey: ["migrations", pipelineId],
    queryFn: () => listMigrations(pipelineId),
    refetchInterval: MIGRATION_LIST_POLL_INTERVAL_MS,
  });

  const runningMigration = migrationsQuery.data?.find((m) => m.status === "running") ?? null;

  const statusQuery = useMigrationStatusPoll(pipelineId, runningMigration?.id ?? null, {
    enabled: runningMigration !== null,
    initialData: runningMigration ?? undefined,
  });

  // Defaults to `true` (not `false`) while this query's own first fetch
  // hasn't resolved yet - deliberately, and not a hypothetical: forcing
  // `false` here before the list ever resolved meant a pipeline whose
  // migration actually *is* running still spent its first render(s) in
  // Analytics mode before flipping to Live once the list settled, and that
  // forced mode flip immediately after mount intermittently broke React
  // Flow's edge rendering on PipelineCanvas's fully-controlled canvas
  // (edges' data stayed correct in React state, but 0 rendered in the DOM -
  // not a timing fluke fixable with a longer wait, the render simply never
  // recovered), found via a repeatedly-flaky e2e run. `true` is the safe
  // default to guess during this brief, real-API-backed window: it's
  // *usually* wrong to guess a migration isn't running before you've even
  // checked, and being briefly, incorrectly "Live" for a pipeline with no
  // migration is a much smaller visual hiccup (no coloring/pulsing to show
  // regardless) than the alternative's actual failure mode.
  const migrationRunning = migrationsQuery.isLoading ? true : runningMigration !== null;

  // Guard against a stale poll result outliving its migration (e.g. the
  // list's next 5s tick already dropped this id from "running") — only
  // trust statusQuery.data while runningMigration still names it.
  const liveStatus = runningMigration ? statusQuery.data : undefined;

  return (
    <>
      {liveStatus?.status === "running" && (
        <button
          type="button"
          onClick={onJumpToMigrations}
          className="mx-4 mt-3 flex w-fit items-center gap-1.5 rounded-full border border-line bg-beam-soft/50 px-3 py-1 text-12 font-medium text-ink transition-colors duration-fast ease-out hover:bg-beam-soft"
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-beam opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-beam" />
          </span>
          Migration running — view in Migrations →
        </button>
      )}
      <PipelineCanvas
        pipelineId={pipelineId}
        stageStates={liveStatus?.stage_states}
        runningSubstep={liveStatus?.progress_substep}
        migrationRunning={migrationRunning}
        onNodeClick={onNodeClick}
      />
    </>
  );
}

/**
 * "Import new run" — attaches a second (third, ...) benchmark run to this
 * *existing* pipeline instead of creating a brand-new one, reusing the
 * Pipelines-home import wizard's own Dropzone for the upload UI (see
 * routes/pipelines-import.tsx) rather than rebuilding it. Server-side, a
 * genuinely new stage in the file gets added, an identical stage gets
 * reused, and a drifted stage (same source_id, different model/prompt/
 * params) is rejected with 422 — see reprompt_api.ingest.persist_trace_file.
 */
function ImportRunDrawer({
  pipelineId,
  open,
  onClose,
}: {
  pipelineId: number;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const importRunMutation = useMutation({
    mutationFn: (file: File) => importIntoExistingPipeline(pipelineId, file),
    onSuccess: () => {
      // Refetch the pipeline's data - stage/trace counts, the DAG (a new
      // run can add stages), rubrics (new stages have none yet), and the
      // runs list all may have changed.
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline-dag", pipelineId] });
      queryClient.invalidateQueries({ queryKey: ["rubrics", pipelineId] });
      queryClient.invalidateQueries({ queryKey: ["runs", pipelineId] });
    },
  });

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      importRunMutation.reset();
      onClose();
    }
  }

  return (
    <DrawerRoot open={open} onOpenChange={handleOpenChange}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>Import new run</DrawerTitle>
          <DrawerDescription>
            Upload another trace file for this pipeline. Matching stages are reused; a
            genuinely new stage is added; a stage whose model or prompt changed is rejected.
          </DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          {!importRunMutation.isSuccess && (
            <Dropzone onFileSelected={(file) => importRunMutation.mutate(file)} />
          )}

          {importRunMutation.isPending && (
            <p className="mt-4 text-13 text-ink-soft" role="status">
              Importing…
            </p>
          )}

          {importRunMutation.isError && (
            <div className="mt-4">
              <p className="mb-2 text-13 font-medium text-parity-fail" role="alert">
                Import failed
              </p>
              <pre className="whitespace-pre-wrap rounded-control bg-beam-soft p-3 font-mono text-12 text-ink">
                {importRunMutation.error instanceof ApiError
                  ? importRunMutation.error.message
                  : "Unknown error"}
              </pre>
              <Button
                variant="secondary"
                size="sm"
                className="mt-3"
                onClick={() => importRunMutation.reset()}
              >
                Try a different file
              </Button>
            </div>
          )}

          {importRunMutation.isSuccess && (
            <ImportRunSuccess result={importRunMutation.data} onDone={onClose} />
          )}
        </DrawerBody>
      </DrawerContent>
    </DrawerRoot>
  );
}

function ImportRunSuccess({
  result,
  onDone,
}: {
  result: ImportResult;
  onDone: () => void;
}) {
  return (
    <div>
      <p className="mb-4 text-14 text-parity-pass">
        Run imported — {result.stage_count} stages, {result.trace_count} traces.
      </p>
      <Button variant="primary" onClick={onDone}>
        Done
      </Button>
    </div>
  );
}

function MigrationsTab({
  pipelineId,
  onBackToCanvas,
}: {
  pipelineId: number;
  onBackToCanvas: () => void;
}) {
  const migrationsQuery = useQuery({
    queryKey: ["migrations", pipelineId],
    queryFn: () => listMigrations(pipelineId),
  });
  // A migration just created in this session by the wizard below - takes
  // priority over whatever the list query returns until it refetches, so
  // the screen doesn't flicker back to the wizard between mutate-success
  // and the next migrations list refetch.
  const [justCreated, setJustCreated] = useState<MigrationOut | null>(null);

  if (migrationsQuery.isLoading) {
    return (
      <p className="text-14 text-ink-soft" role="status">
        Loading migrations…
      </p>
    );
  }

  const existing =
    justCreated ??
    (migrationsQuery.data && migrationsQuery.data.length > 0
      ? migrationsQuery.data[migrationsQuery.data.length - 1]
      : null);

  if (existing) {
    return (
      <MigrationSuccessScreen
        migration={existing}
        pipelineId={String(pipelineId)}
        onBackToCanvas={onBackToCanvas}
      />
    );
  }

  return <NewMigrationWizard pipelineId={pipelineId} onCreated={setJustCreated} />;
}

function StageRubricDrawer({
  pipelineId,
  stageId,
  onClose,
  onViewFullRubric,
}: {
  pipelineId: number;
  stageId: number | null;
  onClose: () => void;
  onViewFullRubric: (stageId: number) => void;
}) {
  const queryClient = useQueryClient();
  const rubricsQuery = useQuery({
    queryKey: ["rubrics", pipelineId],
    queryFn: () => listRubrics(pipelineId),
    enabled: stageId !== null,
  });

  const rubric = rubricsQuery.data?.find((r) => r.stage_id === stageId);

  const approveMutation = useMutation({
    mutationFn: () => {
      if (!rubric) throw new Error("No rubric to approve");
      return approveRubric(rubric.id);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData<RubricOut[]>(["rubrics", pipelineId], (old) =>
        old ? old.map((r) => (r.id === updated.id ? updated : r)) : old
      );
    },
  });

  // Reset the mutation's error/pending state when a different node is
  // clicked - otherwise a failed approval on stage A would still show as
  // errored when the drawer reopens for stage B.
  useEffect(() => {
    approveMutation.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageId]);

  return (
    <DrawerRoot open={stageId !== null} onOpenChange={(open) => !open && onClose()}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>{rubric ? rubric.stage_name : "Stage rubric"}</DrawerTitle>
          <DrawerDescription>
            {rubric ? `Stage id ${rubric.stage_id}` : "No rubric generated for this stage yet."}
          </DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          {rubricsQuery.isLoading && (
            <p className="text-13 text-ink-soft" role="status">
              Loading…
            </p>
          )}
          {!rubricsQuery.isLoading && stageId !== null && !rubric && (
            <p className="text-13 text-ink-soft">
              No rubric has been generated for this stage yet. Generate one from the Rubrics tab.
            </p>
          )}
          {rubric && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Badge variant={rubric.approved ? "pass" : "outline"}>
                  {rubric.approved ? "Approved" : "Needs review"}
                </Badge>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => approveMutation.mutate()}
                  disabled={rubric.approved || approveMutation.isPending}
                >
                  {rubric.approved ? "Approved" : "Approve"}
                </Button>
              </div>

              <div>
                <h3 className="mb-1 text-12 font-medium text-ink">Format checks</h3>
                <ul className="space-y-1">
                  {(rubric.deterministic_checks as DeterministicCheckLike[]).map((check, i) => (
                    <li key={i} className="text-13 text-ink">
                      {describeDeterministicCheck(check)}
                    </li>
                  ))}
                  {rubric.deterministic_checks.length === 0 && (
                    <li className="text-13 text-ink-soft">No format checks yet.</li>
                  )}
                </ul>
              </div>

              <div>
                <h3 className="mb-1 text-12 font-medium text-ink">Content criteria</h3>
                <ul className="space-y-1">
                  {(rubric.judge_criteria as JudgeCriterionLike[]).map((c, i) => (
                    <li key={i} className="text-13 text-ink">
                      {describeJudgeCriterion(c)}
                    </li>
                  ))}
                  {rubric.judge_criteria.length === 0 && (
                    <li className="text-13 text-ink-soft">No content criteria yet.</li>
                  )}
                </ul>
              </div>

              <button
                type="button"
                className="text-13 text-beam hover:underline"
                onClick={() => onViewFullRubric(rubric.stage_id)}
              >
                View full rubric →
              </button>
            </div>
          )}
        </DrawerBody>
      </DrawerContent>
    </DrawerRoot>
  );
}
