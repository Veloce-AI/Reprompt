import { useReducer, useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  addApiKey,
  clearSessionToken,
  deleteApiKey,
  getSessionToken,
  getWorkspaceSettings,
  listApiKeys,
  listConfiguredModels,
  listSystemModels,
  updateWorkspaceSettings,
  type ConfiguredModel,
  type SystemModel,
  type SystemModelPurpose,
} from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { DevSignInButton } from "@/components/dev-sign-in-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// Curated suggestion list only - the provider field is free text server-side
// (see apps/api/src/reprompt_api/models.py's WorkspaceApiKey docstring for
// why: LiteLLM supports many more providers than any fixed list, and "any
// provider" is an explicit project design goal). "Other" reveals a plain
// text input so nothing is actually blocked by this list.
const SUGGESTED_PROVIDERS = ["openai", "anthropic", "gemini"] as const;

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

export default function Settings() {
  // getSessionToken() reads localStorage on every render, so signing in via
  // the dev button below only needs a re-render, not a reload/navigation.
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const isSignedIn = Boolean(getSessionToken());

  if (!isSignedIn) {
    return (
      <AppShell>
        <div className="mx-auto max-w-[640px] p-8 pt-16">
          <h1 className="text-center font-display text-28 font-semibold leading-display text-ink">
            Settings
          </h1>
          {/* Appearance is a local device preference, not workspace data - it
              works (and matters) whether or not you're signed in, so it
              renders above the sign-in gate rather than behind it. */}
          <div className="mt-6">
            <AppearanceCard />
          </div>
          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Sign in to unlock your workspace settings</CardTitle>
              <CardDescription>
                Settings is where your workspace lives — signing in takes a few seconds and
                needs no password, just a one-time email link.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <ul className="space-y-2 text-13 text-ink-soft">
                <li>• Rename your workspace</li>
                <li>• Add BYOK provider API keys (encrypted at rest, never shown again)</li>
                <li>• See every model your keys unlock, with cost and prompt-family info</li>
                <li>• See which models Reprompt itself uses for rubrics, judging and mutation</li>
              </ul>
              <div className="flex flex-col items-center gap-4 border-t border-line pt-6">
                <Link to="/login">
                  <Button variant="primary">Sign in</Button>
                </Link>
                <DevSignInButton onSignedIn={rerender} />
              </div>
            </CardContent>
          </Card>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
    <div className="p-8">
      <h1 className="font-display text-28 font-semibold leading-display text-ink">Settings</h1>
      <p className="mt-1 text-14 text-ink-soft">
        Workspace name and BYOK provider API keys. Keys are encrypted at rest and never shown
        again after saving.
      </p>

      <div className="mt-6 flex flex-col gap-6">
        <AppearanceCard />
        <WorkspaceNameCard />
        <ApiKeysCard />
        <ConfiguredModelsCard />
        <SystemModelsCard />
      </div>
    </div>
    </AppShell>
  );
}

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

function SessionExpiredNotice() {
  clearSessionToken();
  return (
    <p className="text-14 text-parity-fail" role="alert">
      Your session has expired.{" "}
      <Link to="/login" className="text-beam hover:underline">
        Sign in again
      </Link>
      .
    </p>
  );
}

function AppearanceCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>
          Follows your device&apos;s light/dark setting by default. Override it here — your
          choice is saved on this device.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ThemeToggle />
      </CardContent>
    </Card>
  );
}

function WorkspaceNameCard() {
  const queryClient = useQueryClient();
  const [name, setName] = useState<string | null>(null);

  const workspaceQuery = useQuery({
    queryKey: ["settings-workspace"],
    queryFn: getWorkspaceSettings,
    retry: false,
  });

  const renameMutation = useMutation({
    mutationFn: (nextName: string) => updateWorkspaceSettings(nextName),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-workspace"], data);
      setName(null);
    },
  });

  if (workspaceQuery.isError && isUnauthorized(workspaceQuery.error)) {
    return (
      <Card>
        <CardContent className="p-8">
          <SessionExpiredNotice />
        </CardContent>
      </Card>
    );
  }

  const currentName = name ?? workspaceQuery.data?.name ?? "";
  const trimmed = currentName.trim();
  const isDirty = workspaceQuery.data != null && trimmed !== workspaceQuery.data.name;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmed || !isDirty) return;
    renameMutation.mutate(trimmed);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workspace</CardTitle>
        <CardDescription>The name shown for your workspace.</CardDescription>
      </CardHeader>
      <CardContent>
        {workspaceQuery.isLoading && (
          <p className="text-14 text-ink-soft" role="status">
            Loading…
          </p>
        )}
        {workspaceQuery.isError && !isUnauthorized(workspaceQuery.error) && (
          <p className="text-14 text-parity-fail" role="alert">
            Couldn&apos;t load workspace settings.
          </p>
        )}
        {workspaceQuery.data && (
          <form onSubmit={handleSubmit} className="flex max-w-md items-end gap-3">
            <div className="flex-1">
              <label htmlFor="workspace-name" className="mb-2 block text-13 font-medium text-ink">
                Workspace name
              </label>
              <Input
                id="workspace-name"
                value={currentName}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <Button type="submit" variant="primary" disabled={!trimmed || !isDirty || renameMutation.isPending}>
              {renameMutation.isPending ? "Saving…" : "Save"}
            </Button>
          </form>
        )}
        {renameMutation.isError && (
          <p className="mt-2 text-13 text-parity-fail" role="alert">
            {renameMutation.error instanceof ApiError
              ? renameMutation.error.message
              : "Couldn't save the workspace name."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function ApiKeysCard() {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState<string>(SUGGESTED_PROVIDERS[0]);
  const [customProvider, setCustomProvider] = useState("");
  const [apiKey, setApiKey] = useState("");

  const keysQuery = useQuery({
    queryKey: ["settings-api-keys"],
    queryFn: listApiKeys,
    retry: false,
  });

  const addMutation = useMutation({
    mutationFn: () => addApiKey(provider === "other" ? customProvider : provider, apiKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-api-keys"] });
      // Clear the form - the key must never remain visible or resubmittable
      // after a successful save, per "never displayed after save."
      setApiKey("");
      setCustomProvider("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-api-keys"] });
    },
  });

  if (keysQuery.isError && isUnauthorized(keysQuery.error)) {
    return (
      <Card>
        <CardContent className="p-8">
          <SessionExpiredNotice />
        </CardContent>
      </Card>
    );
  }

  const effectiveProvider = (provider === "other" ? customProvider : provider).trim();
  const canAdd = effectiveProvider.length > 0 && apiKey.trim().length >= 4;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canAdd) return;
    addMutation.mutate();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>API keys</CardTitle>
        <CardDescription>
          BYOK provider keys, per the project&apos;s no-hardcoded-keys rule. Encrypted at rest;
          only the last four characters are ever shown again.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {keysQuery.isLoading && (
          <p className="text-14 text-ink-soft" role="status">
            Loading…
          </p>
        )}
        {keysQuery.isError && !isUnauthorized(keysQuery.error) && (
          <p className="text-14 text-parity-fail" role="alert">
            Couldn&apos;t load API keys.
          </p>
        )}

        {keysQuery.data && keysQuery.data.length === 0 && (
          <p className="text-13 text-ink-soft">No API keys configured yet.</p>
        )}

        {keysQuery.data && keysQuery.data.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Added</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {keysQuery.data.map((key) => (
                <TableRow key={key.id}>
                  <TableCell className="font-medium text-ink">{key.provider}</TableCell>
                  <TableCell className="font-mono tabular-nums text-ink-soft">
                    sk-…{key.last_four}
                  </TableCell>
                  <TableCell className="text-ink-soft">{formatDate(key.created_at)}</TableCell>
                  <TableCell>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => deleteMutation.mutate(key.id)}
                      disabled={deleteMutation.isPending}
                      aria-label={`Delete ${key.provider} key`}
                    >
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 border-t border-line pt-6">
          <div className="w-48">
            <label htmlFor="api-key-provider" className="mb-2 block text-13 font-medium text-ink">
              Provider
            </label>
            <Select
              id="api-key-provider"
              value={provider}
              onChange={(event) => setProvider(event.target.value)}
            >
              {SUGGESTED_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
              <option value="other">Other</option>
            </Select>
          </div>

          {provider === "other" && (
            <div className="w-48">
              <label htmlFor="api-key-provider-custom" className="mb-2 block text-13 font-medium text-ink">
                Provider name
              </label>
              <Input
                id="api-key-provider-custom"
                placeholder="e.g. together"
                value={customProvider}
                onChange={(event) => setCustomProvider(event.target.value)}
              />
            </div>
          )}

          <div className="min-w-[240px] flex-1">
            <label htmlFor="api-key-value" className="mb-2 block text-13 font-medium text-ink">
              API key
            </label>
            <Input
              id="api-key-value"
              type="password"
              autoComplete="off"
              placeholder="Paste the key"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>

          <Button type="submit" variant="primary" disabled={!canAdd || addMutation.isPending}>
            {addMutation.isPending ? "Adding…" : "Add API key"}
          </Button>
        </form>

        {addMutation.isError && (
          <p className="text-13 text-parity-fail" role="alert">
            {addMutation.error instanceof ApiError
              ? addMutation.error.message
              : "Couldn't add the API key."}
          </p>
        )}
        {deleteMutation.isError && (
          <p className="text-13 text-parity-fail" role="alert">
            {deleteMutation.error instanceof ApiError
              ? deleteMutation.error.message
              : "Couldn't delete the API key."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function formatCost(perMillion: number | null): string {
  if (perMillion === null) return "—";
  if (perMillion === 0) return "Free (local)";
  return `$${perMillion.toFixed(2)} / 1M tokens`;
}

function ConfiguredModelsCard() {
  const modelsQuery = useQuery({
    queryKey: ["settings-configured-models"],
    queryFn: listConfiguredModels,
    retry: false,
  });

  if (modelsQuery.isError && isUnauthorized(modelsQuery.error)) {
    return (
      <Card>
        <CardContent className="p-8">
          <SessionExpiredNotice />
        </CardContent>
      </Card>
    );
  }

  const byProvider = new Map<string, ConfiguredModel[]>();
  for (const model of modelsQuery.data ?? []) {
    const key = model.provider ?? "other";
    const group = byProvider.get(key) ?? [];
    group.push(model);
    byProvider.set(key, group);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Configured models</CardTitle>
        <CardDescription>
          What you can actually target in a migration right now: local models need no key,
          everything else needs a BYOK key above for that provider. Each model shows the prompt
          rewrite rules (model-card transforms) that will apply when it's picked as a migration
          target.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {modelsQuery.isLoading && (
          <p className="text-14 text-ink-soft" role="status">
            Loading…
          </p>
        )}
        {modelsQuery.isError && !isUnauthorized(modelsQuery.error) && (
          <p className="text-14 text-parity-fail" role="alert">
            Couldn&apos;t load configured models.
          </p>
        )}

        {modelsQuery.data && modelsQuery.data.length === 0 && (
          <p className="text-13 text-ink-soft">No models available yet.</p>
        )}

        {Array.from(byProvider.entries()).map(([provider, providerModels]) => (
          <div key={provider}>
            <h3 className="mb-2 text-13 font-medium capitalize text-ink">{provider}</h3>
            <div className="flex flex-col gap-3">
              {providerModels.map((model) => (
                <div
                  key={model.model}
                  className="rounded-control border border-line p-4 text-13"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono font-medium text-ink">{model.model}</span>
                    <span className="text-12 text-ink-soft">
                      {formatCost(model.input_cost_per_1m)} in /{" "}
                      {formatCost(model.output_cost_per_1m)} out
                    </span>
                  </div>
                  {/* model_card is a required field on the wire contract, but this
                      reads it defensively (optional chaining + fallbacks) rather than
                      assuming the live response always matches the TS type exactly -
                      a version-skewed backend/frontend pair (a real risk in a codebase
                      built across several parallel worktrees that get hand-merged) is
                      not something a compile-time type can catch, and a card that
                      degrades gracefully here beats one that throws and blanks the
                      whole page (see route-error-fallback.tsx's docstring). */}
                  {model.model_card ? (
                    <>
                      <p className="mt-2 text-12 text-ink-soft">
                        Prompt family:{" "}
                        <span className="font-medium text-ink">{model.model_card.family}</span>
                        {model.model_card.is_small_variant && " (small variant)"}
                        {" — "}
                        {model.model_card.description}
                      </p>
                      <ul className="mt-2 flex flex-wrap gap-2">
                        {(model.model_card.rules ?? [])
                          .filter((rule) => rule.will_apply)
                          .map((rule) => (
                            <li
                              key={rule.name}
                              className="rounded-full bg-beam-soft px-2 py-1 text-12 text-beam"
                              title={rule.description}
                            >
                              {rule.name.replace(/_/g, " ")}
                            </li>
                          ))}
                        {(model.model_card.rules ?? []).every((rule) => !rule.will_apply) && (
                          <li className="text-12 text-ink-soft">No transform rules apply.</li>
                        )}
                      </ul>
                    </>
                  ) : (
                    <p className="mt-2 text-12 text-ink-soft">
                      Prompt family info unavailable for this model.
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

const SYSTEM_MODEL_PURPOSE_LABEL: Record<SystemModelPurpose, string> = {
  rubric_generation: "Rubric generation",
  judge: "Judge",
  mutator: "Mutator",
};

const SYSTEM_MODEL_PURPOSE_DESCRIPTION: Record<SystemModelPurpose, string> = {
  rubric_generation: "Reverse-engineers a rubric from your example traces.",
  judge: "Scores each candidate prompt's output against the rubric.",
  mutator: "Proposes and critiques/refines candidate prompt rewrites.",
};

function SystemModelsCard() {
  const modelsQuery = useQuery({
    queryKey: ["settings-system-models"],
    queryFn: listSystemModels,
    retry: false,
  });

  if (modelsQuery.isError && isUnauthorized(modelsQuery.error)) {
    return (
      <Card>
        <CardContent className="p-8">
          <SessionExpiredNotice />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>System models</CardTitle>
        <CardDescription>
          Reprompt's own harness — rubric generation, judging, and prompt mutation — picks a model
          independently from whatever you're optimizing, so a candidate never grades or refines its
          own output. This is what it's actually using right now, given your configured providers
          above.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {modelsQuery.isLoading && (
          <p className="text-14 text-ink-soft" role="status">
            Loading…
          </p>
        )}
        {modelsQuery.isError && !isUnauthorized(modelsQuery.error) && (
          <p className="text-14 text-parity-fail" role="alert">
            Couldn&apos;t load system models.
          </p>
        )}

        {modelsQuery.data && modelsQuery.data.length === 0 && (
          <p className="text-13 text-ink-soft">No system models to show yet.</p>
        )}

        {modelsQuery.data && modelsQuery.data.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Purpose</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Why</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {modelsQuery.data.map((entry: SystemModel) => (
                <TableRow key={entry.purpose}>
                  <TableCell className="text-ink">
                    <div className="font-medium">
                      {SYSTEM_MODEL_PURPOSE_LABEL[entry.purpose] ?? entry.purpose}
                    </div>
                    <div className="text-12 text-ink-soft">
                      {SYSTEM_MODEL_PURPOSE_DESCRIPTION[entry.purpose] ?? ""}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono font-medium text-ink">
                    {entry.selected_model}
                  </TableCell>
                  <TableCell className="text-ink-soft">{entry.reason}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        <p className="mt-4 text-12 text-ink-soft">
          A specific migration can still override the judge or mutator model when you create it;
          this always shows what a new migration would get by default.
        </p>
      </CardContent>
    </Card>
  );
}
