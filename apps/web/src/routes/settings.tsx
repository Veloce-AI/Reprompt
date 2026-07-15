import { useState, type FormEvent } from "react";
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
  updateWorkspaceSettings,
} from "@/lib/api";
import { AppShell } from "@/components/app-shell";
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
  const isSignedIn = Boolean(getSessionToken());

  if (!isSignedIn) {
    return (
      <div className="mx-auto max-w-[640px] p-8 pt-24 text-center">
        <h1 className="font-display text-28 font-semibold leading-display text-ink">Settings</h1>
        <p className="mt-2 text-14 text-ink-soft">Sign in to manage your workspace settings.</p>
        <Link to="/login" className="mt-4 inline-block text-13 text-beam hover:underline">
          Go to sign in
        </Link>
      </div>
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
        <WorkspaceNameCard />
        <ApiKeysCard />
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
