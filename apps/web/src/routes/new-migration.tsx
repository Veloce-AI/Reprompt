import { useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  createMigration,
  getMigrationStatus,
  getPipelineDag,
  listModelOptions,
  startMigration,
  type MigrationOut,
} from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

type WizardStep = "target-model" | "budget" | "confirm";

const STEPS: { id: WizardStep; label: string }[] = [
  { id: "target-model", label: "Target model" },
  { id: "budget", label: "Budget & parity threshold" },
  { id: "confirm", label: "Confirm" },
];

function formatCostPer1M(value: number | null): string {
  if (value == null) return "Unknown";
  if (value === 0) return "Free";
  return `$${value < 1 ? value.toFixed(3) : value.toFixed(2)}`;
}

function formatTokens(value: number | null): string {
  return value == null ? "Unknown" : value.toLocaleString();
}

export default function NewMigration() {
  const { pipelineId } = useParams({ from: "/pipelines/$pipelineId/migrations/new" });
  const pid = Number(pipelineId);
  const [step, setStep] = useState<WizardStep>("target-model");
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [budget, setBudget] = useState("");
  const [parityThresholdPercent, setParityThresholdPercent] = useState("95");

  const dagQuery = useQuery({
    queryKey: ["pipeline-dag", pid],
    queryFn: () => getPipelineDag(pid),
  });
  const modelsQuery = useQuery({
    queryKey: ["model-options", pid],
    queryFn: () => listModelOptions(pid),
  });

  function toggleModel(model: string) {
    setSelectedModels((prev) => {
      const next = new Set(prev);
      if (next.has(model)) next.delete(model);
      else next.add(model);
      return next;
    });
  }

  const migrationMutation = useMutation({
    mutationFn: () =>
      createMigration(pid, {
        target_model_config: { models: [...selectedModels] },
        budget: Number(budget),
        parity_threshold: Number(parityThresholdPercent) / 100,
      }),
  });

  const budgetNumber = Number(budget);
  const parityNumber = Number(parityThresholdPercent);
  const canContinueFromTargetModel = selectedModels.size > 0;
  const canContinueFromBudget =
    budget.trim() !== "" &&
    Number.isFinite(budgetNumber) &&
    budgetNumber > 0 &&
    parityThresholdPercent.trim() !== "" &&
    Number.isFinite(parityNumber) &&
    parityNumber >= 0 &&
    parityNumber <= 100;

  if (migrationMutation.isSuccess) {
    return (
      <MigrationSuccessScreen
        migration={migrationMutation.data}
        pipelineId={pipelineId}
      />
    );
  }

  return (
    <AppShell>
    <div className="p-8">
      <Link
        to="/pipelines/$pipelineId"
        params={{ pipelineId }}
        className="text-13 text-ink-soft hover:text-ink"
      >
        ← Pipeline canvas
      </Link>
      <h1 className="font-display text-28 font-semibold leading-display text-ink">
        New migration
      </h1>
      <p className="mt-1 text-14 text-ink-soft">
        Pick a target model, set a budget and parity threshold, then run the migration.
      </p>

      <ol className="my-6 flex gap-6" aria-label="Migration wizard steps">
        {STEPS.map((s, index) => {
          const isActive = s.id === step;
          const isDone = STEPS.findIndex((x) => x.id === step) > index;
          return (
            <li
              key={s.id}
              className={
                "flex items-center gap-2 text-13 " +
                (isActive ? "font-medium text-ink" : isDone ? "text-parity-pass" : "text-ink-soft")
              }
            >
              <span
                className={
                  "flex h-5 w-5 items-center justify-center rounded-full text-12 font-mono " +
                  (isActive
                    ? "bg-beam text-paper"
                    : isDone
                      ? "bg-parity-pass text-paper"
                      : "border border-line text-ink-soft")
                }
              >
                {index + 1}
              </span>
              {s.label}
            </li>
          );
        })}
      </ol>

      {modelsQuery.isLoading && (
        <p className="text-14 text-ink-soft" role="status">
          Loading models…
        </p>
      )}
      {dagQuery.isError && (
        <p className="text-14 text-parity-fail" role="alert">
          {dagQuery.error instanceof Error ? dagQuery.error.message : "Couldn't load pipeline"}
        </p>
      )}

      {step === "target-model" && (
        <Card>
          <CardContent className="space-y-6 p-8">
            <div>
              <h2 className="mb-1 text-13 font-medium text-ink">Target models</h2>
              <p className="mb-4 text-12 text-ink-soft">
                Select one or more models. The optimizer will try each model per stage and keep the best-scoring result.
              </p>
              {modelsQuery.isLoading ? (
                <p className="text-13 text-ink-soft">Loading available models…</p>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  {(modelsQuery.data ?? []).map((option) => {
                    const checked = selectedModels.has(option.model);
                    return (
                      <label
                        key={option.model}
                        className={
                          "flex cursor-pointer items-start gap-3 rounded-control border p-4 transition-colors " +
                          (checked ? "border-beam bg-beam-soft/40" : "border-line hover:border-beam/40")
                        }
                      >
                        <input
                          type="checkbox"
                          aria-label={option.model}
                          className="mt-0.5 accent-beam"
                          checked={checked}
                          onChange={() => toggleModel(option.model)}
                        />
                        <div className="min-w-0">
                          <p className="font-mono text-13 font-medium text-ink">{option.model}</p>
                          {option.provider && (
                            <p className="text-12 text-ink-soft capitalize">{option.provider}</p>
                          )}
                          <p className="mt-1 text-12 text-ink-soft">
                            {formatCostPer1M(option.input_cost_per_1m)} in /{" "}
                            {formatCostPer1M(option.output_cost_per_1m)} out per 1M tokens
                          </p>
                          <p className="mt-1 text-12 text-ink-soft">
                            Context: {formatTokens(option.max_input_tokens)} tokens
                          </p>
                          <div className="mt-2 flex flex-wrap gap-1">
                            {option.supports_json_mode && (
                              <Badge variant="pass">JSON mode</Badge>
                            )}
                            {option.supports_function_calling && (
                              <Badge variant="pass">Tool use</Badge>
                            )}
                            {!option.requires_api_key && (
                              <Badge variant="neutral">No API key</Badge>
                            )}
                            {option.transform_descriptions.map((desc) => (
                              <Badge key={desc} variant="neutral">{desc}</Badge>
                            ))}
                          </div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
              {!canContinueFromTargetModel && !modelsQuery.isLoading && (
                <p className="mt-3 text-12 text-ink-soft">Select at least one model to continue.</p>
              )}
            </div>

            <div className="flex justify-end">
              <Button
                variant="primary"
                onClick={() => setStep("budget")}
                disabled={!canContinueFromTargetModel}
              >
                Continue to budget & parity threshold
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === "budget" && (
        <Card>
          <CardContent className="space-y-6 p-8">
            <div className="max-w-[360px]">
              <label htmlFor="budget" className="mb-2 block text-13 font-medium text-ink">
                Budget
              </label>
              <p className="mb-2 text-12 text-ink-soft">
                Max optimization spend, in dollars - a hard stop. The migration halts once this is
                reached, whether or not every stage has hit the parity threshold.
              </p>
              <Input
                id="budget"
                type="number"
                min="0"
                step="0.01"
                placeholder="e.g. 25.00"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
              {budget.trim() !== "" && !(budgetNumber > 0) && (
                <p className="mt-2 text-12 text-parity-fail">
                  Budget must be greater than $0. Enter the maximum you're willing to spend.
                </p>
              )}
            </div>

            <div className="max-w-[360px]">
              <label htmlFor="parity-threshold" className="mb-2 block text-13 font-medium text-ink">
                Parity threshold
              </label>
              <p className="mb-2 text-12 text-ink-soft">
                The minimum score (%) a stage must hit against the benchmark to count as passing.
              </p>
              <Input
                id="parity-threshold"
                type="number"
                min="0"
                max="100"
                step="1"
                value={parityThresholdPercent}
                onChange={(e) => setParityThresholdPercent(e.target.value)}
              />
              {parityThresholdPercent.trim() !== "" &&
                !(parityNumber >= 0 && parityNumber <= 100) && (
                  <p className="mt-2 text-12 text-parity-fail">
                    Parity threshold must be between 0 and 100%.
                  </p>
                )}
            </div>

            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setStep("target-model")}>
                Back
              </Button>
              <Button
                variant="primary"
                onClick={() => setStep("confirm")}
                disabled={!canContinueFromBudget}
              >
                Continue to review
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === "confirm" && (
        <Card>
          <CardContent className="space-y-6 p-8">
            <div>
              <h2 className="mb-2 text-13 font-medium text-ink">Target models</h2>
              <ul className="space-y-1">
                {[...selectedModels].map((model) => (
                  <li key={model} className="font-mono text-13 text-ink">
                    {model}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-12 text-ink-soft">
                The optimizer will try each model per stage and keep the best-scoring result.
              </p>
            </div>

            <div>
              <h2 className="mb-2 text-13 font-medium text-ink">Budget & parity threshold</h2>
              <p className="text-14 text-ink">
                Budget: <span className="font-mono tabular-nums">${budgetNumber.toFixed(2)}</span>{" "}
                (hard stop)
              </p>
              <p className="text-14 text-ink">
                Parity threshold:{" "}
                <span className="font-mono tabular-nums">{parityNumber}%</span>
              </p>
            </div>

            {migrationMutation.isError && (
              <p className="text-14 text-parity-fail" role="alert">
                {migrationMutation.error instanceof ApiError
                  ? migrationMutation.error.message
                  : "Couldn't create the migration. Check your connection and try again."}
              </p>
            )}

            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setStep("budget")}>
                Back
              </Button>
              <Button
                variant="primary"
                onClick={() => migrationMutation.mutate()}
                disabled={migrationMutation.isPending}
              >
                {migrationMutation.isPending ? "Creating migration…" : "Run migration"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
      </AppShell>
  );
}

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

function MigrationSuccessScreen({
  migration,
  pipelineId,
}: {
  migration: MigrationOut;
  pipelineId: string;
}) {
  const pid = Number(pipelineId);
  const navigate = useNavigate();
  const [started, setStarted] = useState(false);

  const startMutation = useMutation({
    mutationFn: () => startMigration(pid, migration.id),
    onSuccess: () => setStarted(true),
  });

  const statusQuery = useQuery({
    queryKey: ["migration-status", pid, migration.id],
    queryFn: () => getMigrationStatus(pid, migration.id),
    enabled: started,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "running" ? 2000 : false;
    },
  });

  const status = statusQuery.data;
  const isRunning = status?.status === "running";
  const isTerminal = status && ["completed", "failed", "stopped_early"].includes(status.status);
  const progressPercent =
    status?.progress_current != null && status?.progress_total != null && status.progress_total > 0
      ? Math.round((status.progress_current / status.progress_total) * 100)
      : null;

  return (
    <AppShell>
      <div className="p-8">
        <h1 className="font-display text-28 font-semibold leading-display text-ink">
          New migration
        </h1>
        <Card className="mt-6">
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
                  <Button
                    variant="secondary"
                    onClick={() => navigate({ to: "/pipelines/$pipelineId", params: { pipelineId } })}
                  >
                    Back to pipeline canvas
                  </Button>
                </div>
              </>
            )}

            {started && (
              <div className="mt-2 max-w-[560px]">
                {isRunning && (
                  <>
                    <div className="mb-3 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 animate-pulse rounded-full bg-beam" />
                        <span className="text-13 font-medium text-ink">
                          {status?.progress_stage_name
                            ? `Optimizing: ${status.progress_stage_name}`
                            : "Starting optimizer…"}
                        </span>
                      </div>
                      {progressPercent !== null && (
                        <span className="text-13 tabular-nums text-ink-soft">
                          {status?.progress_current} / {status?.progress_total}
                        </span>
                      )}
                    </div>
                    <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-line">
                      <div
                        className="h-full rounded-full bg-beam transition-all duration-700 ease-out"
                        style={{ width: `${progressPercent ?? 0}%` }}
                      />
                    </div>
                  </>
                )}

                {isTerminal && (
                  <div className="space-y-2">
                    {status?.status === "completed" && (
                      <p className="text-14 text-ink">
                        Optimization complete.{" "}
                        {status.total_cost_usd != null && (
                          <span className="text-ink-soft">
                            Total cost:{" "}
                            <span className="font-mono text-ink">
                              ${status.total_cost_usd.toFixed(4)}
                            </span>
                          </span>
                        )}
                      </p>
                    )}
                    {(status?.status === "failed" || status?.status === "stopped_early") && (
                      <p className="text-14 text-ink">
                        {status.status === "stopped_early" ? "Stopped early" : "Failed"}
                        {status.stop_reason && (
                          <span className="text-ink-soft"> — {status.stop_reason}</span>
                        )}
                      </p>
                    )}
                  </div>
                )}

                {!isTerminal && !isRunning && statusQuery.isLoading && (
                  <p className="text-13 text-ink-soft">Connecting…</p>
                )}

                <div className="mt-6 flex gap-3">
                  {isTerminal && (
                    <Button
                      variant="primary"
                      onClick={() =>
                        navigate({
                          to: "/pipelines/$pipelineId/migrations/$migrationId",
                          params: { pipelineId, migrationId: String(migration.id) },
                        })
                      }
                    >
                      View results →
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    onClick={() => navigate({ to: "/pipelines/$pipelineId", params: { pipelineId } })}
                  >
                    Back to pipeline canvas
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

