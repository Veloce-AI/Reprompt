import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import Settings from "./settings";
import type { ApiKeyOut, ConfiguredModel, SystemModel, WorkspaceSettings } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getSessionToken: vi.fn(),
    clearSessionToken: vi.fn(),
    getWorkspaceSettings: vi.fn(),
    updateWorkspaceSettings: vi.fn(),
    listApiKeys: vi.fn(),
    addApiKey: vi.fn(),
    deleteApiKey: vi.fn(),
    listConfiguredModels: vi.fn(),
    listSystemModels: vi.fn(),
    testModel: vi.fn(),
  };
});

import {
  addApiKey,
  deleteApiKey,
  getSessionToken,
  getWorkspaceSettings,
  listApiKeys,
  listConfiguredModels,
  listSystemModels,
  testModel,
  updateWorkspaceSettings,
} from "@/lib/api";

// TanStack Router's scroll restoration calls window.scrollTo, which jsdom
// doesn't implement - stub it out (same pattern as the other route tests).
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

function baseWorkspace(overrides: Partial<WorkspaceSettings> = {}): WorkspaceSettings {
  return { name: "Acme workspace", ...overrides };
}

function baseSystemModel(overrides: Partial<SystemModel> = {}): SystemModel {
  return {
    purpose: "judge",
    selected_model: "claude-sonnet-4-5",
    reason: "best available",
    ...overrides,
  };
}

function baseKey(overrides: Partial<ApiKeyOut> = {}): ApiKeyOut {
  return {
    id: 1,
    provider: "openai",
    last_four: "a1b2",
    created_at: "2026-01-15T12:00:00Z",
    ...overrides,
  };
}

function baseConfiguredModel(overrides: Partial<ConfiguredModel> = {}): ConfiguredModel {
  return {
    model: "ollama/llama3.1",
    provider: "ollama",
    input_cost_per_1m: 0,
    output_cost_per_1m: 0,
    max_input_tokens: 8192,
    max_output_tokens: 8192,
    supports_json_mode: true,
    supports_function_calling: true,
    requires_api_key: false,
    unlocked: true,
    model_card: {
      family: "llama",
      version: 1,
      description: "Open-weight/self-hosted bucket.",
      is_small_variant: false,
      rules: [
        {
          name: "terseify_if_small",
          description: "Strip hedging/filler phrases.",
          applies_to: "small_only",
          will_apply: false,
        },
      ],
      supports_reasoning: false,
      code_sample: 'complete(model="ollama/llama3.1", messages=[...])',
    },
    ...overrides,
  };
}

function renderSettings() {
  const rootRoute = createRootRoute();
  const settingsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/settings",
    component: Settings,
  });
  const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/pipelines", component: () => null });
  const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: () => null });
  const routeTree = rootRoute.addChildren([settingsRoute, homeRoute, loginRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/settings"] }),
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(getSessionToken).mockReset();
  vi.mocked(getWorkspaceSettings).mockReset();
  vi.mocked(updateWorkspaceSettings).mockReset();
  vi.mocked(listApiKeys).mockReset();
  vi.mocked(addApiKey).mockReset();
  vi.mocked(deleteApiKey).mockReset();
  vi.mocked(listConfiguredModels).mockReset();
  vi.mocked(listSystemModels).mockReset();
  // Default every test to an empty configured-models/system-models list
  // unless a test overrides it - most tests here aren't about these cards
  // specifically.
  vi.mocked(listConfiguredModels).mockResolvedValue([]);
  vi.mocked(listSystemModels).mockResolvedValue([]);
});

describe("Settings", () => {
  it("prompts sign-in when there is no session token", async () => {
    vi.mocked(getSessionToken).mockReturnValue(null);

    renderSettings();

    expect(
      await screen.findByText("Sign in to unlock your workspace settings")
    ).toBeInTheDocument();
    // A real CTA, not just a text link - plus the one-click dev shortcut
    // (import.meta.env.DEV is true under vitest).
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in (dev)" })).toBeInTheDocument();
    // What signing in unlocks is spelled out instead of a dead-end page.
    expect(screen.getByText(/Add BYOK provider API keys/)).toBeInTheDocument();
    expect(getWorkspaceSettings).not.toHaveBeenCalled();
  });

  it("shows the workspace name and the configured API keys once signed in", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([baseKey()]);

    renderSettings();

    expect(await screen.findByDisplayValue("Acme workspace")).toBeInTheDocument();
    // "openai" also appears as a <select> suggestion option, so scope to the
    // table cell (native <table> gives <td> an implicit "cell" role).
    expect(await screen.findByRole("cell", { name: "openai" })).toBeInTheDocument();
    expect(screen.getByText("sk-…a1b2")).toBeInTheDocument();
    // The full key is never shown, only the last four.
    expect(screen.queryByText(/sk-[a-zA-Z0-9]{5,}/)).not.toBeInTheDocument();
  });

  it("saves a renamed workspace", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(updateWorkspaceSettings).mockResolvedValue({ name: "Renamed workspace" });

    renderSettings();

    const nameInput = await screen.findByLabelText("Workspace name");
    fireEvent.change(nameInput, { target: { value: "Renamed workspace" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateWorkspaceSettings).toHaveBeenCalledWith("Renamed workspace");
    });
  });

  it("the save button is disabled until the name actually changes", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);

    renderSettings();

    await screen.findByDisplayValue("Acme workspace");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("adds an API key and clears the form so the key never reappears", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys)
      .mockResolvedValueOnce([]) // initial load
      .mockResolvedValueOnce([baseKey({ provider: "anthropic", last_four: "z9y8" })]); // after add
    vi.mocked(addApiKey).mockResolvedValue(
      baseKey({ provider: "anthropic", last_four: "z9y8" })
    );

    renderSettings();

    await screen.findByText(/No API keys configured yet/);

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "anthropic" } });
    const keyInput = screen.getByLabelText("API key");
    fireEvent.change(keyInput, { target: { value: "sk-ant-abcdz9y8" } });
    fireEvent.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() => {
      expect(addApiKey).toHaveBeenCalledWith("anthropic", "sk-ant-abcdz9y8");
    });

    // Form clears the raw key input after a successful save.
    await waitFor(() => {
      expect((keyInput as HTMLInputElement).value).toBe("");
    });

    // The newly added key shows up with only its last four visible.
    expect(await screen.findByRole("cell", { name: "anthropic" })).toBeInTheDocument();
    expect(screen.getByText("sk-…z9y8")).toBeInTheDocument();
  });

  it("shows a free-text provider input when 'Other' is selected", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(addApiKey).mockResolvedValue(baseKey({ provider: "together", last_four: "wxyz" }));

    renderSettings();

    await screen.findByText(/No API keys configured yet/);

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "other" } });
    const customProviderInput = await screen.findByLabelText("Provider name");
    fireEvent.change(customProviderInput, { target: { value: "together" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-togetherwxyz" } });
    fireEvent.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() => {
      expect(addApiKey).toHaveBeenCalledWith("together", "sk-togetherwxyz");
    });
  });

  it("deletes an API key", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys)
      .mockResolvedValueOnce([baseKey()])
      .mockResolvedValueOnce([]);
    vi.mocked(deleteApiKey).mockResolvedValue(undefined);

    renderSettings();

    await screen.findByRole("cell", { name: "openai" });
    fireEvent.click(screen.getByRole("button", { name: "Delete openai key" }));

    await waitFor(() => {
      expect(deleteApiKey).toHaveBeenCalledWith(1);
    });

    await waitFor(() => {
      expect(screen.getByText(/No API keys configured yet/)).toBeInTheDocument();
    });
  });

  it("the add button is disabled until a provider and key are entered", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);

    renderSettings();

    await screen.findByText(/No API keys configured yet/);
    expect(screen.getByRole("button", { name: "Add API key" })).toBeDisabled();
  });

  it("shows configured models grouped by provider with model-card info", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([baseKey()]);
    vi.mocked(listConfiguredModels).mockResolvedValue([
      baseConfiguredModel(),
      baseConfiguredModel({
        model: "gpt-4o",
        provider: "openai",
        input_cost_per_1m: 2.5,
        output_cost_per_1m: 10,
        requires_api_key: true,
        model_card: {
          family: "openai",
          version: 1,
          description: "GPT-family models.",
          is_small_variant: false,
          rules: [],
          supports_reasoning: true,
          code_sample: 'complete(model="gpt-4o", messages=[...], reasoning_effort="medium")',
        },
      }),
    ]);

    renderSettings();

    expect(await screen.findByText("Configured models")).toBeInTheDocument();
    expect(await screen.findByText("ollama/llama3.1")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("ollama")).toBeInTheDocument();
    expect(screen.getByText("openai", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText(/Free \(local\)/)).toBeInTheDocument();
  });

  it("shows a thinking-mode badge and a copyable code sample for a reasoning-capable model", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });

    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([baseKey()]);
    vi.mocked(listConfiguredModels).mockResolvedValue([
      baseConfiguredModel({
        model: "gpt-4o",
        provider: "openai",
        requires_api_key: true,
        model_card: {
          family: "openai",
          version: 1,
          description: "GPT-family models.",
          is_small_variant: false,
          rules: [],
          supports_reasoning: true,
          code_sample: 'complete(model="gpt-4o", messages=[...], reasoning_effort="medium")',
        },
      }),
    ]);

    renderSettings();

    expect(await screen.findByText("Thinking mode")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Code sample"));
    expect(
      screen.getByText('complete(model="gpt-4o", messages=[...], reasoning_effort="medium")')
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        'complete(model="gpt-4o", messages=[...], reasoning_effort="medium")'
      );
    });
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("tests an unlocked model and shows the real latency on success", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([baseKey()]);
    vi.mocked(listConfiguredModels).mockResolvedValue([baseConfiguredModel()]);
    vi.mocked(testModel).mockResolvedValue({
      model: "ollama/llama3.1",
      provider: "ollama",
      latency_ms: 342,
      content_preview: "ok",
    });

    renderSettings();

    await screen.findByText("ollama/llama3.1");
    // Scoped to index 0: the curated model's own "Test" button renders
    // before the "Test any model" free-text section's identically-labeled
    // submit button further down the card.
    fireEvent.click(screen.getAllByRole("button", { name: "Test" })[0]);

    expect(await screen.findByText("Works — 342ms")).toBeInTheDocument();
    expect(testModel).toHaveBeenCalledWith("ollama/llama3.1");
  });

  it("shows 'Test failed' when a model test errors", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([baseKey()]);
    vi.mocked(listConfiguredModels).mockResolvedValue([baseConfiguredModel()]);
    vi.mocked(testModel).mockRejectedValue(new Error("No API key configured"));

    renderSettings();

    await screen.findByText("ollama/llama3.1");
    // Scoped to index 0: the curated model's own "Test" button renders
    // before the "Test any model" free-text section's identically-labeled
    // submit button further down the card.
    fireEvent.click(screen.getAllByRole("button", { name: "Test" })[0]);

    expect(await screen.findByText("Test failed")).toBeInTheDocument();
    // The failure reason is visible text now, not just a hover tooltip -
    // a screenshot/report of a failed test used to be undiagnosable
    // without knowing to hover over the badge.
    expect(
      await screen.findByText("Test failed — check your connection and try again.")
    ).toBeInTheDocument();
  });

  it("lets a user test any model string, not just ones in the curated list", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([baseKey()]);
    vi.mocked(listConfiguredModels).mockResolvedValue([baseConfiguredModel()]);
    vi.mocked(testModel).mockResolvedValue({
      model: "nvidia_nim/z-ai/glm-5.2",
      provider: "nvidia_nim",
      latency_ms: 512,
      content_preview: "ok",
    });

    renderSettings();

    await screen.findByText("ollama/llama3.1");
    fireEvent.change(screen.getByLabelText("Model string to test"), {
      target: { value: "nvidia_nim/z-ai/glm-5.2" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Test" })[1]);

    expect(await screen.findByText("Works — 512ms")).toBeInTheDocument();
    expect(testModel).toHaveBeenCalledWith("nvidia_nim/z-ai/glm-5.2");
  });

  it("shows a locked curated model (e.g. NVIDIA NIM) with an inline unlock, not hidden", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(listConfiguredModels).mockResolvedValue([
      baseConfiguredModel(),
      baseConfiguredModel({
        model: "nvidia_nim/meta/llama-3.1-405b-instruct",
        provider: "nvidia_nim",
        requires_api_key: true,
        unlocked: false,
        input_cost_per_1m: null,
        output_cost_per_1m: null,
        model_card: {
          family: "llama",
          version: 1,
          description: "Open-weight/self-hosted bucket.",
          is_small_variant: false,
          rules: [],
          supports_reasoning: false,
          code_sample: 'complete(model="nvidia_nim/meta/llama-3.1-405b-instruct", messages=[...])',
        },
      }),
    ]);
    vi.mocked(addApiKey).mockResolvedValue({
      id: 9,
      provider: "nvidia_nim",
      last_four: "9999",
      created_at: "2026-01-15T12:00:00Z",
    });

    renderSettings();

    // Locked model is visible (not filtered out) with a clear unlock path.
    const modelName = await screen.findByText("nvidia_nim/meta/llama-3.1-405b-instruct");
    const modelCard = modelName.closest("div")?.parentElement as HTMLElement;
    expect(within(modelCard).getByText("API key required")).toBeInTheDocument();

    // "Add API key" is also the ApiKeysCard form's own submit button above -
    // scope to the locked model's own card to click the right one.
    fireEvent.click(within(modelCard).getByRole("button", { name: "Add API key" }));

    // The drawer portals outside the render root as a dialog - ApiKeysCard's
    // own "API key" field is a separate, simultaneously-present element, so
    // scope every subsequent query into the dialog specifically.
    const dialog = await screen.findByRole("dialog");
    const keyInput = within(dialog).getByLabelText("API key");
    fireEvent.change(keyInput, { target: { value: "nvapi-test-key-000000000000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save key & unlock models" }));

    await waitFor(() => {
      expect(addApiKey).toHaveBeenCalledWith("nvidia_nim", "nvapi-test-key-000000000000");
    });
  });

  it("shows only no-key-required models when no BYOK key is configured", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(listConfiguredModels).mockResolvedValue([baseConfiguredModel()]);

    renderSettings();

    expect(await screen.findByText("ollama/llama3.1")).toBeInTheDocument();
    expect(screen.queryByText("gpt-4o")).not.toBeInTheDocument();
  });

  it("shows an empty state when no models are available yet", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(listConfiguredModels).mockResolvedValue([]);

    renderSettings();

    expect(await screen.findByText("No models available yet.")).toBeInTheDocument();
  });

  it("shows the system models Reprompt's own harness is auto-selecting", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(listSystemModels).mockResolvedValue([
      baseSystemModel({ purpose: "rubric_generation", selected_model: "claude-sonnet-4-5" }),
      baseSystemModel({ purpose: "judge", selected_model: "claude-sonnet-4-5" }),
      baseSystemModel({ purpose: "mutator", selected_model: "gpt-4o" }),
    ]);

    renderSettings();

    expect(await screen.findByText("System models")).toBeInTheDocument();
    expect(await screen.findByText("Rubric generation")).toBeInTheDocument();
    expect(screen.getByText("Judge")).toBeInTheDocument();
    expect(screen.getByText("Mutator")).toBeInTheDocument();
    expect(screen.getAllByText("claude-sonnet-4-5")).toHaveLength(2);
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getAllByText("best available")).toHaveLength(3);
  });

  it("shows an empty state when no system models are returned", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(listSystemModels).mockResolvedValue([]);

    renderSettings();

    expect(await screen.findByText("No system models to show yet.")).toBeInTheDocument();
  });
});
