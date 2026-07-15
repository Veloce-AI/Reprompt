import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveRubric,
  listMigrations,
  listPipelines,
  listRubrics,
  updatePipeline,
  type MigrationOut,
  type PipelineSummary,
  type RubricOut,
} from "@/lib/api";
import {
  describeDeterministicCheck,
  describeJudgeCriterion,
  type DeterministicCheckLike,
  type JudgeCriterionLike,
} from "@/lib/rubric-format";
import { AppShell } from "@/components/app-shell";
import { PipelineCanvas } from "@/components/pipeline-canvas";
import { RubricReviewPanel } from "@/components/rubric-review-panel";
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

export type WorkspaceTab = "canvas" | "data" | "rubrics" | "migrations";

export const WORKSPACE_TABS: readonly WorkspaceTab[] = ["canvas", "data", "rubrics", "migrations"];

const TAB_LABELS: Record<WorkspaceTab, string> = {
  canvas: "Canvas",
  data: "Data",
  rubrics: "Rubrics",
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

  // No single GET /pipelines/{id} endpoint exists (only the list and /dag) -
  // reuse the list the home screen already fetches rather than adding one.
  const pipelinesQuery = useQuery({ queryKey: ["pipelines"], queryFn: listPipelines });
  const pipeline = pipelinesQuery.data?.find((p) => p.id === pid);

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
      <div className="flex h-full min-h-[calc(100vh-1px)] flex-col">
        <div className="border-b border-line px-8 py-4">
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

          <nav className="mt-4 flex gap-1" aria-label="Pipeline workspace tabs">
            {WORKSPACE_TABS.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => goToTab(t)}
                aria-current={tab === t ? "page" : undefined}
                className={cn(
                  "rounded-control px-3 py-1.5 text-13 font-medium transition-colors duration-fast ease-out",
                  tab === t
                    ? "bg-beam-soft text-beam"
                    : "text-ink-soft hover:bg-beam-soft/50 hover:text-ink"
                )}
              >
                {TAB_LABELS[t]}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1 overflow-y-auto">
          {tab === "canvas" && (
            <PipelineCanvas
              pipelineId={pid}
              onNodeClick={(stageId) => setSelectedStageId(stageId)}
            />
          )}
          {tab === "data" && (
            <div className="p-8">
              <p className="font-display text-20 font-semibold text-ink">Coming soon</p>
              <p className="mt-2 text-14 text-ink-soft">
                A dashboard over this pipeline's benchmark and migration data lands in a later
                phase.
              </p>
            </div>
          )}
          {tab === "rubrics" && (
            <div className="p-8">
              <RubricReviewPanel pipelineId={pid} />
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
    </AppShell>
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
