import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveAllRubrics,
  approveRubric,
  generateRubric,
  getPipelineDag,
  listRubrics,
  updateRubric,
  type RubricOut,
  type RubricUpdate,
} from "@/lib/api";
import {
  describeDeterministicCheck,
  describeDownstreamField,
  describeJudgeCriterion,
  isEditableCheckType,
  type DeterministicCheckLike,
  type JudgeCriterionLike,
} from "@/lib/rubric-format";
import { AppShell } from "@/components/app-shell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function RubricReview() {
  const { pipelineId } = useParams({ from: "/pipelines/$pipelineId/rubrics" });
  const pid = Number(pipelineId);
  const queryClient = useQueryClient();

  const [model, setModel] = useState("");
  const [generatingAll, setGeneratingAll] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const {
    data: rubrics,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["rubrics", pid],
    queryFn: () => listRubrics(pid),
  });

  const { data: dag } = useQuery({
    queryKey: ["dag", pid],
    queryFn: () => getPipelineDag(pid),
  });

  const approveAllMutation = useMutation({
    mutationFn: () => approveAllRubrics(pid),
    onSuccess: (updated) => queryClient.setQueryData(["rubrics", pid], updated),
  });

  const allStages = dag ? Object.values(dag.stages) : [];
  const allApproved = (rubrics ?? []).length > 0 && (rubrics ?? []).every((r) => r.approved);

  async function handleGenerateAll() {
    const trimmedModel = model.trim();
    if (!trimmedModel) {
      setGenerateError("Enter a model name first (e.g. openai/gpt-4o).");
      return;
    }
    setGenerateError(null);
    setGeneratingAll(true);
    try {
      const results: RubricOut[] = [];
      for (const stage of allStages) {
        const rubric = await generateRubric(pid, stage.id, trimmedModel);
        results.push(rubric);
      }
      queryClient.setQueryData(["rubrics", pid], results);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Failed to generate rubrics.");
    } finally {
      setGeneratingAll(false);
    }
  }

  return (
    <AppShell>
    <div className="p-8">
      <div className="mb-2 flex items-start justify-between">
        <div>
          <Link
            to="/pipelines/$pipelineId"
            params={{ pipelineId }}
            className="text-13 text-ink-soft hover:text-ink"
          >
            ← Pipeline canvas
          </Link>
          <h1 className="font-display text-28 font-semibold leading-display text-ink">
            Rubric review
          </h1>
          <p className="mt-1 text-14 text-ink-soft">
            Review and edit each stage&apos;s checklist before running a migration.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Input
            placeholder="Model (e.g. openai/gpt-4o)"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-56"
            aria-label="Model for rubric generation"
          />
          <Button
            variant="secondary"
            onClick={handleGenerateAll}
            disabled={generatingAll || allStages.length === 0}
          >
            {generatingAll ? "Generating…" : "Generate all rubrics"}
          </Button>

          {/* "Approve all" is always available, not gated on a per-stage
              "viewed" flag: the rubrics are all rendered on this one page (not
              paginated or hidden behind a click-to-expand), so a reviewer who
              scans the page has already seen everything there is to see. A
              "viewed" flag would need its own persisted state and would only
              protect against a reviewer who scrolls past without reading -
              which "Approve all" doesn't uniquely enable anyway (per-stage
              "Approve" has the exact same risk). Simpler to keep one clear
              rule than a second, weaker safety net. */}
          {rubrics && rubrics.length > 0 && (
            <Button
              variant="primary"
              onClick={() => approveAllMutation.mutate()}
              disabled={allApproved || approveAllMutation.isPending}
            >
              {allApproved ? "All stages approved" : "Approve all"}
            </Button>
          )}
        </div>
      </div>

      {generateError && (
        <p className="mb-4 text-13 text-parity-fail" role="alert">
          {generateError}
        </p>
      )}

      {isLoading && (
        <p className="text-14 text-ink-soft" role="status">
          Loading rubrics…
        </p>
      )}

      {isError && (
        <p className="text-14 text-parity-fail" role="alert">
          {error instanceof Error ? error.message : "Couldn't load rubrics"}
        </p>
      )}

      {rubrics && rubrics.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center">
            <p className="font-display text-20 font-semibold text-ink">No rubrics yet</p>
            <p className="mt-2 text-14 text-ink-soft">
              Enter a model name above and click &ldquo;Generate all rubrics&rdquo; to generate rubrics for
              every stage automatically.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="space-y-6 mt-6">
        {rubrics?.map((rubric) => (
          <StageRubricCard key={rubric.id} rubric={rubric} pipelineId={pid} model={model} />
        ))}
      </div>
    </div>
    </AppShell>
  );
}

function StageRubricCard({
  rubric,
  pipelineId,
  model,
}: {
  rubric: RubricOut;
  pipelineId: number;
  model: string;
}) {
  const queryClient = useQueryClient();

  function replaceInCache(updated: RubricOut) {
    queryClient.setQueryData<RubricOut[]>(["rubrics", pipelineId], (old) =>
      old ? old.map((r) => (r.id === updated.id ? updated : r)) : old
    );
  }

  const patchMutation = useMutation({
    mutationFn: (patch: RubricUpdate) => updateRubric(rubric.id, patch),
    onSuccess: replaceInCache,
  });

  const approveMutation = useMutation({
    mutationFn: () => approveRubric(rubric.id),
    onSuccess: replaceInCache,
  });

  const regenerateMutation = useMutation({
    mutationFn: () => generateRubric(pipelineId, rubric.stage_id, model.trim()),
    onSuccess: replaceInCache,
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>{rubric.stage_name}</CardTitle>
          <CardDescription>Stage id {rubric.stage_id}</CardDescription>
        </div>
        <div className="flex items-center gap-3">
          {regenerateMutation.isError && (
            <p className="text-12 text-parity-fail">
              {regenerateMutation.error instanceof Error
                ? regenerateMutation.error.message
                : "Regeneration failed"}
            </p>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => regenerateMutation.mutate()}
            disabled={regenerateMutation.isPending || !model.trim()}
            title={!model.trim() ? "Enter a model name at the top of the page first" : undefined}
          >
            {regenerateMutation.isPending ? "Generating…" : "Regenerate"}
          </Button>
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
      </CardHeader>
      <CardContent className="space-y-6">
        <DeterministicSection
          checks={rubric.deterministic_checks as DeterministicCheckLike[]}
          onChange={(checks) => patchMutation.mutate({ deterministic_checks: checks })}
        />
        <JudgeCriteriaSection
          criteria={rubric.judge_criteria as JudgeCriterionLike[]}
          onChange={(criteria) => patchMutation.mutate({ judge_criteria: criteria })}
        />
        <DownstreamContractSection
          fields={rubric.downstream_contract}
          onChange={(fields) => patchMutation.mutate({ downstream_contract: fields })}
        />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Format checks (deterministic_checks)
// ---------------------------------------------------------------------------

function DeterministicSection({
  checks,
  onChange,
}: {
  checks: DeterministicCheckLike[];
  onChange: (checks: DeterministicCheckLike[]) => void;
}) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [newKeys, setNewKeys] = useState("");

  function deleteAt(index: number) {
    onChange(checks.filter((_, i) => i !== index));
  }

  function saveEdit(index: number, next: DeterministicCheckLike) {
    onChange(checks.map((c, i) => (i === index ? next : c)));
    setEditingIndex(null);
  }

  function addFromInput() {
    const keys = newKeys
      .split(",")
      .map((k) => k.trim())
      .filter(Boolean);
    if (keys.length === 0) return;
    onChange([...checks, { type: "required_keys", keys }]);
    setNewKeys("");
  }

  return (
    <section aria-labelledby={`format-checks-${checks.length}-heading`}>
      <h2 className="mb-2 text-13 font-medium text-ink">Format checks</h2>
      <ul className="space-y-2">
        {checks.map((check, index) => (
          <li
            key={(check.id as string | undefined) ?? index}
            className="flex items-start justify-between gap-3 rounded-control border border-line p-3"
          >
            {editingIndex === index && isEditableCheckType(check.type) ? (
              <DeterministicCheckEditor
                check={check}
                onSave={(next) => saveEdit(index, next)}
                onCancel={() => setEditingIndex(null)}
              />
            ) : (
              <>
                <p className="text-13 text-ink">{describeDeterministicCheck(check)}</p>
                <div className="flex shrink-0 gap-2">
                  {isEditableCheckType(check.type) && (
                    <Button variant="ghost" size="sm" onClick={() => setEditingIndex(index)}>
                      Edit
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => deleteAt(index)}>
                    Delete
                  </Button>
                </div>
              </>
            )}
          </li>
        ))}
        {checks.length === 0 && <li className="text-13 text-ink-soft">No format checks yet.</li>}
      </ul>
      <div className="mt-3 flex gap-2">
        <Input
          placeholder="e.g. currency, revenue"
          aria-label="Add a format check: required keys, comma separated"
          value={newKeys}
          onChange={(e) => setNewKeys(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addFromInput()}
        />
        <Button variant="secondary" onClick={addFromInput}>
          Add criterion
        </Button>
      </div>
    </section>
  );
}

function DeterministicCheckEditor({
  check,
  onSave,
  onCancel,
}: {
  check: DeterministicCheckLike;
  onSave: (next: DeterministicCheckLike) => void;
  onCancel: () => void;
}) {
  // Both branches' state is declared unconditionally (rules-of-hooks) - the
  // check's type doesn't change while this editor is mounted, so only one
  // branch's values ever get used per instance.
  const [keysValue, setKeysValue] = useState((check.keys ?? []).join(", "));
  const [minValue, setMinValue] = useState(check.min_length != null ? String(check.min_length) : "");
  const [maxValue, setMaxValue] = useState(check.max_length != null ? String(check.max_length) : "");

  if (check.type === "required_keys") {
    return (
      <div className="flex w-full flex-wrap items-center gap-2">
        <Input
          value={keysValue}
          onChange={(e) => setKeysValue(e.target.value)}
          aria-label="Required keys, comma separated"
        />
        <Button
          size="sm"
          onClick={() =>
            onSave({
              ...check,
              keys: keysValue
                .split(",")
                .map((k) => k.trim())
                .filter(Boolean),
            })
          }
        >
          Save
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-wrap items-center gap-2">
      <Input
        type="number"
        value={minValue}
        onChange={(e) => setMinValue(e.target.value)}
        placeholder="Min"
        aria-label="Minimum length"
        className="w-24"
      />
      <Input
        type="number"
        value={maxValue}
        onChange={(e) => setMaxValue(e.target.value)}
        placeholder="Max"
        aria-label="Maximum length"
        className="w-24"
      />
      <Button
        size="sm"
        onClick={() =>
          onSave({
            ...check,
            min_length: minValue === "" ? undefined : Number(minValue),
            max_length: maxValue === "" ? undefined : Number(maxValue),
          })
        }
      >
        Save
      </Button>
      <Button variant="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Content criteria (judge_criteria)
// ---------------------------------------------------------------------------

function JudgeCriteriaSection({
  criteria,
  onChange,
}: {
  criteria: JudgeCriterionLike[];
  onChange: (criteria: JudgeCriterionLike[]) => void;
}) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [newName, setNewName] = useState("");

  function deleteAt(index: number) {
    onChange(criteria.filter((_, i) => i !== index));
  }

  function saveEdit(index: number, next: JudgeCriterionLike) {
    onChange(criteria.map((c, i) => (i === index ? next : c)));
    setEditingIndex(null);
  }

  function addFromInput() {
    const name = newName.trim();
    if (!name) return;
    onChange([...criteria, { name, weight: 1, description: "" }]);
    setNewName("");
  }

  return (
    <section>
      <h2 className="mb-2 text-13 font-medium text-ink">Content criteria</h2>
      <ul className="space-y-2">
        {criteria.map((criterion, index) => (
          <li
            key={index}
            className="flex items-start justify-between gap-3 rounded-control border border-line p-3"
          >
            {editingIndex === index ? (
              <JudgeCriterionEditor
                criterion={criterion}
                onSave={(next) => saveEdit(index, next)}
                onCancel={() => setEditingIndex(null)}
              />
            ) : (
              <>
                <div>
                  <p className="text-13 text-ink">{describeJudgeCriterion(criterion)}</p>
                  <Badge variant="neutral" className="mt-1 font-mono">
                    weight {criterion.weight}
                  </Badge>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setEditingIndex(index)}>
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => deleteAt(index)}>
                    Delete
                  </Button>
                </div>
              </>
            )}
          </li>
        ))}
        {criteria.length === 0 && <li className="text-13 text-ink-soft">No content criteria yet.</li>}
      </ul>
      <div className="mt-3 flex gap-2">
        <Input
          placeholder="e.g. Covers all key entities"
          aria-label="Add a content criterion"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addFromInput()}
        />
        <Button variant="secondary" onClick={addFromInput}>
          Add criterion
        </Button>
      </div>
    </section>
  );
}

function JudgeCriterionEditor({
  criterion,
  onSave,
  onCancel,
}: {
  criterion: JudgeCriterionLike;
  onSave: (next: JudgeCriterionLike) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(criterion.name);
  const [weight, setWeight] = useState(String(criterion.weight));
  const [description, setDescription] = useState(criterion.description ?? "");

  return (
    <div className="flex w-full flex-col gap-2">
      <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="Criterion name" />
      <Input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        aria-label="Criterion description"
      />
      <div className="flex items-center gap-2">
        <Input
          type="number"
          step="0.1"
          value={weight}
          onChange={(e) => setWeight(e.target.value)}
          aria-label="Criterion weight"
          className="w-24"
        />
        <Button
          size="sm"
          onClick={() => onSave({ name: name.trim(), weight: Number(weight) || 0, description })}
        >
          Save
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Downstream contract
// ---------------------------------------------------------------------------

function DownstreamContractSection({
  fields,
  onChange,
}: {
  fields: string[];
  onChange: (fields: string[]) => void;
}) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [newField, setNewField] = useState("");

  function deleteAt(index: number) {
    onChange(fields.filter((_, i) => i !== index));
  }

  function startEdit(index: number) {
    setEditingIndex(index);
    setEditValue(fields[index]);
  }

  function saveEdit(index: number) {
    const value = editValue.trim();
    if (!value) return;
    onChange(fields.map((f, i) => (i === index ? value : f)));
    setEditingIndex(null);
  }

  function addFromInput() {
    const value = newField.trim();
    if (!value) return;
    onChange([...fields, value]);
    setNewField("");
  }

  return (
    <section>
      <h2 className="mb-2 text-13 font-medium text-ink">Downstream contract</h2>
      <p className="mb-2 text-12 text-ink-soft">
        The only fields the next stage actually reads — output can drift elsewhere without breaking
        parity.
      </p>
      <ul className="space-y-2">
        {fields.map((field, index) => (
          <li
            key={index}
            className="flex items-center justify-between gap-3 rounded-control border border-line p-3"
          >
            {editingIndex === index ? (
              <div className="flex w-full items-center gap-2">
                <Input
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  aria-label="Downstream field name"
                />
                <Button size="sm" onClick={() => saveEdit(index)}>
                  Save
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setEditingIndex(null)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <>
                <p className="font-mono text-13 text-ink">{describeDownstreamField(field)}</p>
                <div className="flex shrink-0 gap-2">
                  <Button variant="ghost" size="sm" onClick={() => startEdit(index)}>
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => deleteAt(index)}>
                    Delete
                  </Button>
                </div>
              </>
            )}
          </li>
        ))}
        {fields.length === 0 && <li className="text-13 text-ink-soft">No downstream fields recorded yet.</li>}
      </ul>
      <div className="mt-3 flex gap-2">
        <Input
          placeholder="e.g. currency"
          aria-label="Add a downstream contract field"
          value={newField}
          onChange={(e) => setNewField(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addFromInput()}
        />
        <Button variant="secondary" onClick={addFromInput}>
          Add criterion
        </Button>
      </div>
    </section>
  );
}
