import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, addApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DrawerRoot,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from "@/components/ui/drawer";

/**
 * Inline BYOK key entry, opened from the migration wizard's model picker
 * when the user clicks "Add API key" on a model whose provider has no key
 * configured yet — so unlocking a model never requires a detour through
 * Settings. Posts to the exact same upsert endpoint Settings' own key form
 * uses (`POST /settings/api-keys` via `addApiKey`) and invalidates the same
 * `["settings-api-keys"]` query key, so both this wizard's lock state and
 * the Settings page pick the new key up immediately.
 */
export function AddApiKeyDrawer({
  provider,
  open,
  onOpenChange,
}: {
  /** Provider to add a key for (comes from the locked model's own metadata). */
  provider: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");

  const addKeyMutation = useMutation({
    mutationFn: () => addApiKey(provider, apiKey.trim()),
    onSuccess: () => {
      // Same keys Settings' own ApiKeysCard invalidates, plus the
      // configured-models list that's derived from them.
      queryClient.invalidateQueries({ queryKey: ["settings-api-keys"] });
      queryClient.invalidateQueries({ queryKey: ["settings-configured-models"] });
      setApiKey("");
      onOpenChange(false);
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!apiKey.trim() || addKeyMutation.isPending) return;
    addKeyMutation.mutate();
  }

  return (
    <DrawerRoot
      open={open}
      onOpenChange={(next) => {
        if (!next) addKeyMutation.reset();
        onOpenChange(next);
      }}
    >
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>Add an API key</DrawerTitle>
          <DrawerDescription>
            Unlock <span className="capitalize">{provider}</span> models by adding your own key.
            It's encrypted at rest, never shown again after saving, and also appears in Settings.
          </DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <label
                htmlFor="wizard-api-key-provider"
                className="mb-2 block text-13 font-medium text-ink"
              >
                Provider
              </label>
              <Input id="wizard-api-key-provider" value={provider} disabled readOnly />
            </div>
            <div>
              <label
                htmlFor="wizard-api-key-value"
                className="mb-2 block text-13 font-medium text-ink"
              >
                API key
              </label>
              <Input
                id="wizard-api-key-value"
                type="password"
                autoComplete="off"
                placeholder="sk-…"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </div>
            {addKeyMutation.isError && (
              <p className="text-13 text-parity-fail" role="alert">
                {addKeyMutation.error instanceof ApiError
                  ? addKeyMutation.error.message
                  : "Couldn't save the key. Check it and try again."}
              </p>
            )}
            <Button
              type="submit"
              variant="primary"
              disabled={!apiKey.trim() || addKeyMutation.isPending}
            >
              {addKeyMutation.isPending ? "Saving key…" : "Save key & unlock models"}
            </Button>
          </form>
        </DrawerBody>
      </DrawerContent>
    </DrawerRoot>
  );
}
