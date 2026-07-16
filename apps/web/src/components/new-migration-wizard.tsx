import { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  createMigration,
  getModelCard,
  getPipelineDag,
  listModelOptions,
  type MigrationOut,
  type ModelCardInfo,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

type WizardStep = "target-model" | "budget" | "confirm";

type ModelFamily = "anthropic" | "gemini" | "openai" | "llama" | "generic";

const _OPEN_WEIGHT_MARKERS = ["llama", "mistral", "mixtral", "gemma", "qwen", "deepseek", "phi", "vicuna", "falcon", "starcoder"];

function resolveFamily(model: string): ModelFamily {
  const lower = model.toLowerCase();
  if (_OPEN_WEIGHT_MARKERS.some((m) => lower.includes(m))) return "llama";
  if (lower.includes("claude")) return "anthropic";
  if (lower.includes("gemini")) return "gemini";
  if (lower.includes("gpt")) return "openai";
  return "generic";
}

const FAMILY_TRANSFORM_LABELS: Record<ModelFamily, string> = {
  anthropic: "XML-tagged sections (Anthropic convention)",
  gemini: "Markdown headers (Gemini convention)",
  openai: "Compression on mini/small variants only",
  llama: "Compression on small variants only",
  generic: "Compression on small variants only",
};

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

/**
 * The migration wizard's create-a-migration half, extracted from the old
 * standalone `/pipelines/$pipelineId/migrations/new` route (see
 * DEV_TRACKER.md's "Phase 1 — Unified pipeline workspace") so it can be
 * rendered as the Migrations tab of pipeline-workspace.tsx when no
 * Migration exists yet for this pipeline. Unchanged from the original route
 * component except: `pipelineId` arrives as a prop instead of `useParams`,
 * there's no `<AppShell>`/header/back-link (the workspace supplies one
 * shared header), and instead of rendering `<MigrationSuccessScreen>`
 * itself on success it calls `onCreated` — the tab container
 * (pipeline-workspace.tsx's MigrationsTab) decides what to render next.
 */
export function NewMigrationWizard({
  pipelineId,
  onCreated,
}: {
  pipelineId: number;
  onCreated: (migration: MigrationOut) => void;
}) {
  const [step, setStep] = useState<WizardStep>("target-model");
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [budget, setBudget] = useState("");
  const [parityThresholdPercent, setParityThresholdPercent] = useState("95");
  const [modelCards, setModelCards] = useState<Record<string, ModelCardInfo | null>>({});
  // Advanced, optional per-stage override - collapsed by default, most
  // migrations never need it (see DEV_TRACKER.md's "Per-stage target model
  // override" note). Keyed by stage db id (string, matching the DAG's own
  // node ids); a stage with no entry here just uses `selectedModels` like
  // every stage did before this section existed.
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [stageOverrides, setStageOverrides] = useState<Record<string, Set<string>>>({});

  const dagQuery = useQuery({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(pipelineId),
  });
  const modelsQuery = useQuery({
    queryKey: ["model-options", pipelineId],
    queryFn: () => listModelOptions(pipelineId),
  });

  // Fetch model card info for each available model
  useEffect(() => {
    if (!modelsQuery.data) return;
    const fetchCards = async () => {
      const cards: Record<string, ModelCardInfo | null> = {};
      for (const option of modelsQuery.data) {
        try {
          cards[option.model] = await getModelCard(option.model);
        } catch {
          cards[option.model] = null;
        }
      }
      setModelCards(cards);
    };
    fetchCards();
  }, [modelsQuery.data]);

  function toggleModel(model: string) {
    setSelectedModels((prev) => {
      const next = new Set(prev);
      if (next.has(model)) next.delete(model);
      else next.add(model);
      return next;
    });
  }

  // A stage with no entry in `stageOverrides` yet reads as "= the global
  // selection" - only becomes a real per-stage override once the user
  // actually touches its checkboxes (seeded from the global selection at
  // that moment, then diverges independently).
  function toggleStageOverrideModel(stageId: string, model: string) {
    setStageOverrides((prev) => {
      const current = prev[stageId] ?? new Set(selectedModels);
      const next = new Set(current);
      if (next.has(model)) next.delete(model);
      else next.add(model);
      return { ...prev, [stageId]: next };
    });
  }

  function stageModelsFor(stageId: string): Set<string> {
    return stageOverrides[stageId] ?? selectedModels;
  }

  function setsEqual(a: Set<string>, b: Set<string>): boolean {
    return a.size === b.size && [...a].every((v) => b.has(v));
  }

  // Only a stage whose selection actually diverges from the global default
  // is worth sending - keeps "no customization" the common, clean payload
  // (an untouched or reverted-back-to-default stage sends nothing), per
  // the additive stage_overrides schema's own design.
  const stageOverridesPayload: Record<string, string[]> = {};
  for (const [stageId, models] of Object.entries(stageOverrides)) {
    if (!setsEqual(models, selectedModels)) {
      stageOverridesPayload[stageId] = [...models];
    }
  }
  const hasEmptyStageOverride = Object.values(stageOverridesPayload).some(
    (models) => models.length === 0
  );
  const stages = Object.values(dagQuery.data?.stages ?? {}).sort((a, b) => a.id - b.id);

  const migrationMutation = useMutation({
    mutationFn: () =>
      createMigration(pipelineId, {
        target_model_config: {
          models: [...selectedModels],
          // Omit the key entirely (not `{}`) when nothing was customized -
          // keeps the common-case payload/stored shape identical to before
          // this section existed.
          ...(Object.keys(stageOverridesPayload).length > 0
            ? { stage_overrides: stageOverridesPayload }
            : {}),
        },
        budget: Number(budget),
        parity_threshold: Number(parityThresholdPercent) / 100,
      }),
  });

  useEffect(() => {
    if (migrationMutation.isSuccess && migrationMutation.data) {
      onCreated(migrationMutation.data);
    }
    // onCreated is expected to be referentially stable enough for this
    // effect's purposes (it just swaps local state in the parent) - only
    // re-fire when the mutation itself actually succeeds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [migrationMutation.isSuccess, migrationMutation.data]);

  const budgetNumber = Number(budget);
  const parityNumber = Number(parityThresholdPercent);
  const canContinueFromTargetModel = selectedModels.size > 0 && !hasEmptyStageOverride;
  const canContinueFromBudget =
    budget.trim() !== "" &&
    Number.isFinite(budgetNumber) &&
    budgetNumber > 0 &&
    parityThresholdPercent.trim() !== "" &&
    Number.isFinite(parityNumber) &&
    parityNumber >= 0 &&
    parityNumber <= 100;

  // Parent switches to <MigrationSuccessScreen> as soon as onCreated fires -
  // render nothing in the meantime rather than a flash of the wizard.
  if (migrationMutation.isSuccess) {
    return null;
  }

  return (
    <div>
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
                    const family = resolveFamily(option.model);
                    const modelCard = modelCards[option.model];
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
                        <div className="min-w-0 flex-1">
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
                            <Badge variant="neutral">{FAMILY_TRANSFORM_LABELS[family]}</Badge>
                          </div>
                          {modelCard && (
                            <div className="mt-3 space-y-1 rounded bg-ink-soft/5 p-3">
                              <p className="text-11 font-medium uppercase tracking-wide text-ink-soft">
                                Model transform rules
                              </p>
                              {modelCard.rules.length > 0 ? (
                                <ul className="space-y-1 text-12 text-ink">
                                  {modelCard.rules.map((rule) => (
                                    <li
                                      key={rule.name}
                                      className={
                                        rule.will_apply
                                          ? "flex items-start gap-1 text-ink"
                                          : "flex items-start gap-1 text-ink-soft line-through"
                                      }
                                    >
                                      <span className="mt-0.5 flex-shrink-0">
                                        {rule.will_apply ? "✓" : "—"}
                                      </span>
                                      <span>
                                        <strong>{rule.name}:</strong> {rule.description}
                                      </span>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <p className="text-12 text-ink-soft italic">No transform rules</p>
                              )}
                            </div>
                          )}
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

            {selectedModels.size > 0 && (
              <div>
                <button
                  type="button"
                  onClick={() => setShowAdvanced((v) => !v)}
                  aria-expanded={showAdvanced}
                  className="text-13 font-medium text-beam hover:underline"
                >
                  {showAdvanced ? "Hide advanced: customize per stage" : "Advanced: customize per stage"}
                </button>
                {showAdvanced && (
                  <div className="mt-3 space-y-4 rounded-control border border-line p-4">
                    <p className="text-12 text-ink-soft">
                      Optional — override the target model(s) for individual stages. Every stage
                      starts pre-selected with the models chosen above; a stage's selection is
                      only sent as an override once it actually differs from that default.
                    </p>
                    {dagQuery.isLoading ? (
                      <p className="text-13 text-ink-soft">Loading stages…</p>
                    ) : (
                      stages.map((stage) => {
                        const stageId = String(stage.id);
                        const stageModels = stageModelsFor(stageId);
                        const isOverridden = stageId in stageOverridesPayload;
                        return (
                          <div
                            key={stage.id}
                            className="border-t border-line pt-3 first:border-t-0 first:pt-0"
                          >
                            <div className="mb-2 flex items-center gap-2 text-13 font-medium text-ink">
                              <span>{stage.name}</span>
                              {isOverridden && <Badge variant="pass">Customized</Badge>}
                            </div>
                            <div className="flex flex-wrap gap-3">
                              {(modelsQuery.data ?? []).map((option) => {
                                const checked = stageModels.has(option.model);
                                return (
                                  <label
                                    key={option.model}
                                    className="flex cursor-pointer items-center gap-1.5 text-12 text-ink"
                                  >
                                    <input
                                      type="checkbox"
                                      aria-label={`${option.model} for ${stage.name}`}
                                      className="accent-beam"
                                      checked={checked}
                                      onChange={() => toggleStageOverrideModel(stageId, option.model)}
                                    />
                                    <span className="font-mono">{option.model}</span>
                                  </label>
                                );
                              })}
                            </div>
                            {stageModels.size === 0 && (
                              <p className="mt-1 text-12 text-parity-fail">
                                Select at least one model for {stage.name}, or match it back to
                                the default selection above to remove the override.
                              </p>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                )}
              </div>
            )}

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

            {Object.keys(stageOverridesPayload).length > 0 && (
              <div>
                <h2 className="mb-2 text-13 font-medium text-ink">Per-stage overrides</h2>
                <ul className="space-y-1">
                  {Object.entries(stageOverridesPayload).map(([stageId, models]) => {
                    const stageName =
                      stages.find((s) => String(s.id) === stageId)?.name ?? `Stage ${stageId}`;
                    return (
                      <li key={stageId} className="text-13 text-ink">
                        {stageName}: <span className="font-mono">{models.join(", ")}</span>
                      </li>
                    );
                  })}
                </ul>
                <p className="mt-2 text-12 text-ink-soft">
                  These stages use their own model list instead of the target models above.
                </p>
              </div>
            )}

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
  );
}
