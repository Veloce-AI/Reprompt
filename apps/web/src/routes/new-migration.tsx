import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  createMigration,
  getPipelineDag,
  listModelOptions,
  type ModelOption,
  type StageInfo,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
  const navigate = useNavigate();

  const [step, setStep] = useState<WizardStep>("target-model");
  const [defaultModel, setDefaultModel] = useState("");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
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

  const stages: StageInfo[] = useMemo(() => {
    if (!dagQuery.data) return [];
    return Object.values(dagQuery.data.stages).sort((a, b) => a.id - b.id);
  }, [dagQuery.data]);

  const modelByName = useMemo(() => {
    const map = new Map<string, ModelOption>();
    for (const option of modelsQuery.data ?? []) map.set(option.model, option);
    return map;
  }, [modelsQuery.data]);

  function setOverride(stageId: number, model: string) {
    setOverrides((prev) => {
      const next = { ...prev };
      if (model === "") {
        delete next[String(stageId)];
      } else {
        next[String(stageId)] = model;
      }
      return next;
    });
  }

  function effectiveModel(stageId: number): string {
    return overrides[String(stageId)] || defaultModel;
  }

  const migrationMutation = useMutation({
    mutationFn: () =>
      createMigration(pid, {
        target_model_config: { default: defaultModel, stages: overrides },
        budget: Number(budget),
        parity_threshold: Number(parityThresholdPercent) / 100,
      }),
  });

  const budgetNumber = Number(budget);
  const parityNumber = Number(parityThresholdPercent);
  const canContinueFromTargetModel = defaultModel.trim().length > 0;
  const canContinueFromBudget =
    budget.trim() !== "" &&
    Number.isFinite(budgetNumber) &&
    budgetNumber > 0 &&
    parityThresholdPercent.trim() !== "" &&
    Number.isFinite(parityNumber) &&
    parityNumber >= 0 &&
    parityNumber <= 100;

  const overrideCount = Object.keys(overrides).length;

  if (migrationMutation.isSuccess) {
    const migration = migrationMutation.data;
    return (
      <div className="mx-auto max-w-[1440px] p-8">
        <h1 className="font-display text-28 font-semibold leading-display text-ink">
          New migration
        </h1>
        <Card className="mt-6">
          <CardContent className="p-8">
            <div className="mb-2 flex items-center gap-2 text-14 font-medium text-ink">
              <span>Migration #{migration.id} created</span>
              <Badge variant="outline">Pending</Badge>
            </div>
            <p className="mb-6 max-w-[640px] text-14 text-ink-soft">
              The optimizer that actually runs migrations hasn&apos;t been built yet, so this
              migration is saved with its configuration but won&apos;t run anything. Once the
              optimizer ships, this record is what it will pick up and execute.
            </p>
            <div className="flex gap-3">
              <Button
                variant="primary"
                onClick={() =>
                  navigate({ to: "/pipelines/$pipelineId", params: { pipelineId } })
                }
              >
                Back to pipeline canvas
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1440px] p-8">
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

      {dagQuery.isLoading && (
        <p className="text-14 text-ink-soft" role="status">
          Loading pipeline stages…
        </p>
      )}
      {dagQuery.isError && (
        <p className="text-14 text-parity-fail" role="alert">
          {dagQuery.error instanceof Error ? dagQuery.error.message : "Couldn't load pipeline"}
        </p>
      )}

      {step === "target-model" && dagQuery.data && (
        <Card>
          <CardContent className="space-y-6 p-8">
            <div>
              <label htmlFor="default-model" className="mb-2 block text-13 font-medium text-ink">
                Default target model
              </label>
              <p className="mb-2 text-12 text-ink-soft">
                Applied to every stage unless you override it below.
              </p>
              <Select
                id="default-model"
                value={defaultModel}
                onChange={(e) => setDefaultModel(e.target.value)}
                disabled={modelsQuery.isLoading}
              >
                <option value="" disabled>
                  {modelsQuery.isLoading ? "Loading models…" : "Select a model"}
                </option>
                {(modelsQuery.data ?? []).map((option) => (
                  <option key={option.model} value={option.model}>
                    {option.model}
                  </option>
                ))}
              </Select>
              {!canContinueFromTargetModel && (
                <p className="mt-2 text-12 text-ink-soft">
                  Select a default model to continue.
                </p>
              )}
              {defaultModel && modelByName.has(defaultModel) && (
                <ModelFacts option={modelByName.get(defaultModel)!} />
              )}
            </div>

            <div>
              <h2 className="mb-2 text-13 font-medium text-ink">Per-stage overrides</h2>
              <p className="mb-3 text-12 text-ink-soft">
                Optional - leave a stage on "Use default" to migrate it to the default model above.
                {overrideCount > 0 &&
                  ` ${overrideCount} stage${overrideCount === 1 ? "" : "s"} overridden.`}
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Stage</TableHead>
                    <TableHead>Current model</TableHead>
                    <TableHead>Target model</TableHead>
                    <TableHead>Cost / 1M tokens</TableHead>
                    <TableHead>Context window</TableHead>
                    <TableHead>JSON mode</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stages.map((stage) => {
                    const effective = effectiveModel(stage.id);
                    const facts = modelByName.get(effective);
                    return (
                      <TableRow key={stage.id}>
                        <TableCell className="font-medium text-ink">{stage.name}</TableCell>
                        <TableCell className="font-mono text-ink-soft">{stage.model}</TableCell>
                        <TableCell>
                          <Select
                            aria-label={`Target model for ${stage.name}`}
                            value={overrides[String(stage.id)] ?? ""}
                            onChange={(e) => setOverride(stage.id, e.target.value)}
                          >
                            <option value="">
                              Use default{defaultModel ? ` (${defaultModel})` : ""}
                            </option>
                            {(modelsQuery.data ?? []).map((option) => (
                              <option key={option.model} value={option.model}>
                                {option.model}
                              </option>
                            ))}
                          </Select>
                        </TableCell>
                        <TableCell className="font-mono tabular-nums">
                          {facts ? formatCostPer1M(facts.input_cost_per_1m) : "—"}
                        </TableCell>
                        <TableCell className="font-mono tabular-nums">
                          {facts ? formatTokens(facts.max_input_tokens) : "—"}
                        </TableCell>
                        <TableCell>
                          {facts ? (
                            <Badge variant={facts.supports_json_mode ? "pass" : "outline"}>
                              {facts.supports_json_mode ? "Supported" : "Not supported"}
                            </Badge>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
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
              <h2 className="mb-2 text-13 font-medium text-ink">Target model</h2>
              <p className="text-14 text-ink">
                Default: <span className="font-mono">{defaultModel}</span>
              </p>
              {overrideCount === 0 ? (
                <p className="mt-1 text-13 text-ink-soft">No per-stage overrides.</p>
              ) : (
                <ul className="mt-2 space-y-1">
                  {Object.entries(overrides).map(([stageId, model]) => {
                    const stage = stages.find((s) => s.id === Number(stageId));
                    return (
                      <li key={stageId} className="text-13 text-ink">
                        {stage?.name ?? `Stage ${stageId}`}:{" "}
                        <span className="font-mono">{model}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
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
  );
}

function ModelFacts({ option }: { option: ModelOption }) {
  return (
    <div className="mt-3 flex flex-wrap gap-4 rounded-control border border-line bg-beam-soft/40 p-3 text-12 text-ink-soft">
      <span>
        Cost / 1M tokens:{" "}
        <span className="font-mono text-ink">
          {formatCostPer1M(option.input_cost_per_1m)} in / {formatCostPer1M(option.output_cost_per_1m)} out
        </span>
      </span>
      <span>
        Context window:{" "}
        <span className="font-mono text-ink">{formatTokens(option.max_input_tokens)}</span>
      </span>
      <span>
        JSON mode:{" "}
        <Badge variant={option.supports_json_mode ? "pass" : "outline"}>
          {option.supports_json_mode ? "Supported" : "Not supported"}
        </Badge>
      </span>
      <span>
        Tool use:{" "}
        <Badge variant={option.supports_function_calling ? "pass" : "outline"}>
          {option.supports_function_calling ? "Supported" : "Not supported"}
        </Badge>
      </span>
      {!option.requires_api_key && <Badge variant="neutral">No API key required</Badge>}
    </div>
  );
}
