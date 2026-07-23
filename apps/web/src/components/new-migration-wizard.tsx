import { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import {
  ApiError,
  createMigration,
  getModelCard,
  getPipelineDag,
  listApiKeys,
  listModelOptions,
  lookupModelOption,
  type MigrationOut,
  type ModelCardInfo,
  type ModelOption,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { AddApiKeyDrawer } from "@/components/add-api-key-drawer";
import { PrismExplainer } from "@/components/prism-explainer";

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

/**
 * One model's picker card - checkbox + cost/context/capability info +
 * transform rules, locked or not. Shared by the curated grid and the
 * custom-model lookup list (see `NewMigrationWizard`'s "Add a custom
 * model" section) so a model looks and behaves identically regardless of
 * which list it came from - the only thing that differs between the two
 * lists is *how a model got there*, not how it's presented.
 */
function ModelOptionCard({
  option,
  checked,
  locked,
  modelCard,
  onToggle,
  onRequestKey,
  onRemove,
}: {
  option: ModelOption;
  checked: boolean;
  locked: boolean;
  modelCard: ModelCardInfo | null | undefined;
  onToggle: () => void;
  onRequestKey: () => void;
  /** Only custom (looked-up, non-curated) models can be removed from the
   * list entirely - curated models are always present. */
  onRemove?: () => void;
}) {
  return (
    <label
      className={
        "flex items-start gap-3 rounded-control border p-4 transition-colors " +
        (locked
          ? "cursor-default border-line opacity-60"
          : checked
            ? "cursor-pointer border-beam bg-beam-soft/40"
            : "cursor-pointer border-line hover:border-beam/40")
      }
    >
      <input
        type="checkbox"
        aria-label={option.model}
        className="mt-0.5 accent-beam"
        checked={checked}
        disabled={locked}
        onChange={onToggle}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p className="min-w-0 break-all font-mono text-13 font-medium text-ink">{option.model}</p>
          {onRemove && (
            <button
              type="button"
              aria-label={`Remove ${option.model}`}
              className="shrink-0 rounded-control p-0.5 text-ink-soft hover:bg-beam-soft hover:text-ink"
              onClick={(event) => {
                event.preventDefault();
                onRemove();
              }}
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
        {option.provider && <p className="text-12 text-ink-soft capitalize">{option.provider}</p>}
        {locked && option.provider && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant="neutral">API key required</Badge>
            <button
              type="button"
              className="text-12 font-medium text-beam hover:underline"
              onClick={(event) => {
                // Inside a <label>: don't let the click also reach the
                // (disabled) checkbox.
                event.preventDefault();
                onRequestKey();
              }}
            >
              Add API key
            </button>
          </div>
        )}
        <p className="mt-1 text-12 text-ink-soft">
          {formatCostPer1M(option.input_cost_per_1m)} in / {formatCostPer1M(option.output_cost_per_1m)} out
          per 1M tokens
        </p>
        <p className="mt-1 text-12 text-ink-soft">Context: {formatTokens(option.max_input_tokens)} tokens</p>
        <div className="mt-2 flex flex-wrap gap-1">
          {option.supports_json_mode && <Badge variant="pass">JSON mode</Badge>}
          {option.supports_function_calling && <Badge variant="pass">Tool use</Badge>}
          {!option.requires_api_key && <Badge variant="neutral">No API key</Badge>}
          {option.transform_descriptions.map((desc) => (
            <Badge key={desc} variant="neutral">
              {desc}
            </Badge>
          ))}
        </div>
        {modelCard && (
          <div className="mt-3 space-y-1 rounded bg-ink-soft/5 p-3">
            <p className="text-11 font-medium uppercase tracking-wide text-ink-soft">Model transform rules</p>
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
                    <span className="mt-0.5 flex-shrink-0">{rule.will_apply ? "✓" : "—"}</span>
                    <span className="min-w-0 flex-1">
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
  // Which provider the inline add-a-key drawer is open for; null = closed.
  const [keyDrawerProvider, setKeyDrawerProvider] = useState<string | null>(null);
  // "Add a custom model" - any LiteLLM model string beyond the curated
  // list (e.g. an NVIDIA NIM/OpenRouter model not hand-curated). Looked up
  // live via lookupMutation; successful lookups accumulate here so they
  // render alongside the curated grid using the same ModelOptionCard.
  const [customModelInput, setCustomModelInput] = useState("");
  const [customModels, setCustomModels] = useState<ModelOption[]>([]);

  const dagQuery = useQuery({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(pipelineId),
  });
  const modelsQuery = useQuery({
    queryKey: ["model-options", pipelineId],
    queryFn: () => listModelOptions(pipelineId),
  });
  // Same query key as Settings' ApiKeysCard, so adding a key from either
  // place updates both. `retry: false` + the isSuccess guard below mean an
  // unauthenticated session (401 here) simply shows every model unlocked -
  // exactly the wizard's pre-lock behavior, never a lockout.
  const apiKeysQuery = useQuery({
    queryKey: ["settings-api-keys"],
    queryFn: listApiKeys,
    retry: false,
  });
  const configuredProviders = new Set(
    (apiKeysQuery.data ?? []).map((key) => key.provider.toLowerCase())
  );

  // A model is locked when it needs a provider API key this workspace
  // doesn't have yet. Locked models stay visible (greyed out, with an
  // inline "Add API key" affordance) rather than hidden - the user should
  // see what's possible.
  function isLocked(option: ModelOption): boolean {
    return (
      apiKeysQuery.isSuccess &&
      option.requires_api_key &&
      option.provider != null &&
      !configuredProviders.has(option.provider.toLowerCase())
    );
  }

  // Fetch model card info for every available model - curated plus any
  // looked-up custom ones, merged rather than replaced so a re-run
  // triggered by a new custom model doesn't drop already-fetched cards.
  useEffect(() => {
    const allOptions = [...(modelsQuery.data ?? []), ...customModels];
    if (allOptions.length === 0) return;
    const fetchCards = async () => {
      const cards: Record<string, ModelCardInfo | null> = {};
      for (const option of allOptions) {
        try {
          cards[option.model] = await getModelCard(option.model);
        } catch {
          cards[option.model] = null;
        }
      }
      setModelCards((prev) => ({ ...prev, ...cards }));
    };
    fetchCards();
  }, [modelsQuery.data, customModels]);

  const lookupMutation = useMutation({
    mutationFn: () => lookupModelOption(pipelineId, customModelInput.trim()),
    onSuccess: (option) => {
      setCustomModels((prev) => [...prev.filter((m) => m.model !== option.model), option]);
      setCustomModelInput("");
    },
  });

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
      <div className="mt-2 flex items-center gap-2">
        <p className="text-12 text-ink-soft">
          Running this migration hands each stage's prompt to{" "}
          <span className="font-medium text-ink">Prism</span> — a self-evolving prompt optimizer
        </p>
        <PrismExplainer />
      </div>

      {keyDrawerProvider != null && (
        <AddApiKeyDrawer
          provider={keyDrawerProvider}
          open
          onOpenChange={(open) => {
            if (!open) setKeyDrawerProvider(null);
          }}
        />
      )}

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
                  {(modelsQuery.data ?? []).map((option) => (
                    <ModelOptionCard
                      key={option.model}
                      option={option}
                      checked={!isLocked(option) && selectedModels.has(option.model)}
                      locked={isLocked(option)}
                      modelCard={modelCards[option.model]}
                      onToggle={() => toggleModel(option.model)}
                      onRequestKey={() => setKeyDrawerProvider(option.provider)}
                    />
                  ))}
                </div>
              )}
              {!canContinueFromTargetModel && !modelsQuery.isLoading && (
                <p className="mt-3 text-12 text-ink-soft">Select at least one model to continue.</p>
              )}

              {/* Beyond the curated list: any LiteLLM model string an
                  aggregator provider (NVIDIA NIM, OpenRouter, ...) actually
                  offers, not just what's hand-curated above - "any provider"
                  is this project's own stated design goal (see
                  WorkspaceApiKey's docstring in apps/api/models.py). */}
              <div className="mt-4 border-t border-line pt-4">
                <p className="mb-2 text-13 font-medium text-ink">Add a custom model</p>
                <p className="mb-3 text-12 text-ink-soft">
                  Any LiteLLM model string, e.g.{" "}
                  <code className="font-mono text-11">nvidia_nim/meta/llama-3.1-8b-instruct</code> or{" "}
                  <code className="font-mono text-11">openrouter/anthropic/claude-3.7-sonnet</code>.
                </p>
                <form
                  className="flex items-start gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!customModelInput.trim() || lookupMutation.isPending) return;
                    lookupMutation.mutate();
                  }}
                >
                  <Input
                    aria-label="Custom model string"
                    placeholder="provider/org/model-name"
                    value={customModelInput}
                    onChange={(event) => setCustomModelInput(event.target.value)}
                    className="font-mono"
                  />
                  <Button type="submit" variant="secondary" disabled={!customModelInput.trim() || lookupMutation.isPending}>
                    {lookupMutation.isPending ? "Looking up…" : "Look up"}
                  </Button>
                </form>
                {lookupMutation.isError && (
                  <p className="mt-2 text-13 text-parity-fail" role="alert">
                    {lookupMutation.error instanceof ApiError
                      ? lookupMutation.error.message
                      : "Couldn't look up that model."}
                  </p>
                )}
                {customModels.length > 0 && (
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    {customModels.map((option) => (
                      <ModelOptionCard
                        key={option.model}
                        option={option}
                        checked={!isLocked(option) && selectedModels.has(option.model)}
                        locked={isLocked(option)}
                        modelCard={modelCards[option.model]}
                        onToggle={() => toggleModel(option.model)}
                        onRequestKey={() => setKeyDrawerProvider(option.provider)}
                        onRemove={() => {
                          setCustomModels((prev) => prev.filter((m) => m.model !== option.model));
                          setSelectedModels((prev) => {
                            const next = new Set(prev);
                            next.delete(option.model);
                            return next;
                          });
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
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
                                const locked = isLocked(option);
                                const checked = !locked && stageModels.has(option.model);
                                return (
                                  <label
                                    key={option.model}
                                    className={
                                      "flex items-center gap-1.5 text-12 text-ink " +
                                      (locked ? "cursor-default opacity-50" : "cursor-pointer")
                                    }
                                  >
                                    <input
                                      type="checkbox"
                                      aria-label={`${option.model} for ${stage.name}`}
                                      className="accent-beam"
                                      checked={checked}
                                      disabled={locked}
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
