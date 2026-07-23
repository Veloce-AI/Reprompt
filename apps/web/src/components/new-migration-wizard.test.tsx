import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NewMigrationWizard } from "./new-migration-wizard";
import type { DagResponse, ModelOption, ModelCardInfo } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getPipelineDag: vi.fn(),
    listModelOptions: vi.fn(),
    listOpenRouterCatalog: vi.fn(),
    createMigration: vi.fn(),
    getModelCard: vi.fn(),
    listApiKeys: vi.fn(),
    addApiKey: vi.fn(),
  };
});

import {
  addApiKey,
  createMigration,
  getPipelineDag,
  listApiKeys,
  listModelOptions,
  listOpenRouterCatalog,
  getModelCard,
} from "@/lib/api";
import type { ApiKeyOut } from "@/lib/api";

function keyFor(provider: string, id = 1): ApiKeyOut {
  return { id, provider, last_four: "abcd", created_at: "2026-01-15T12:00:00Z" };
}

function baseDag(): DagResponse {
  return {
    pipeline_id: 1,
    layers: [{ stage_ids: [10] }, { stage_ids: [11] }],
    stages: {
      "10": {
        id: 10,
        name: "Extract",
        model: "gpt-4o",
        avg_tokens_in: 100,
        avg_tokens_out: 50,
        avg_latency_ms: 500,
        trace_count: 0,
        total_cost_usd: null,
      },
      "11": {
        id: 11,
        name: "Summarize",
        model: "gpt-4o",
        avg_tokens_in: 200,
        avg_tokens_out: 80,
        avg_latency_ms: 700,
        trace_count: 0,
        total_cost_usd: null,
      },
    },
    edges: [{ from_stage_id: 10, to_stage_id: 11 }],
  };
}

function baseModels(): ModelOption[] {
  return [
    {
      model: "gpt-4o-mini",
      provider: "openai",
      input_cost_per_1m: 0.15,
      output_cost_per_1m: 0.6,
      max_input_tokens: 128000,
      max_output_tokens: 16384,
      supports_json_mode: true,
      supports_function_calling: true,
      requires_api_key: true,
      family: "openai",
      transform_descriptions: ["Strip hedging/filler phrases and fold each paragraph's sentences into terse imperative bullet points."],
    },
    {
      model: "claude-haiku-4-5",
      provider: "anthropic",
      input_cost_per_1m: 1,
      output_cost_per_1m: 5,
      max_input_tokens: 200000,
      max_output_tokens: 64000,
      supports_json_mode: true,
      supports_function_calling: true,
      requires_api_key: true,
      family: "anthropic",
      transform_descriptions: ["Wrap recognized labeled sections in XML-ish tags, per Anthropic's documented prompting guidance."],
    },
  ];
}

function baseModelCard(family: string): ModelCardInfo {
  return {
    family,
    version: 1,
    description: `Family card for ${family}`,
    is_small_variant: false,
    rules: [
      {
        name: "test_rule",
        description: "A test rule",
        applies_to: "all",
        will_apply: true,
      },
    ],
    supports_reasoning: false,
    code_sample: `complete(model="${family}-example", messages=[...])`,
  };
}

function renderWizard(onCreated: (m: unknown) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NewMigrationWizard pipelineId={1} onCreated={onCreated as never} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(getPipelineDag).mockReset();
  vi.mocked(listModelOptions).mockReset();
  vi.mocked(listOpenRouterCatalog).mockReset();
  vi.mocked(createMigration).mockReset();
  vi.mocked(getModelCard).mockReset();
  vi.mocked(listApiKeys).mockReset();
  vi.mocked(addApiKey).mockReset();
  // Default: keys exist for both providers baseModels() uses, so every
  // pre-existing test sees the wizard exactly as it behaved before the
  // locked-model states existed. Lock-specific tests override this.
  vi.mocked(listApiKeys).mockResolvedValue([keyFor("openai", 1), keyFor("anthropic", 2)]);
  // Default: empty catalog - only the new OpenRouter-picker-specific test
  // below needs a populated one.
  vi.mocked(listOpenRouterCatalog).mockResolvedValue([]);
});

describe("NewMigrationWizard — pre-start Prism reference", () => {
  it("mentions Prism and offers the 'How Prism works' explainer before a migration is created", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());

    renderWizard(vi.fn());

    expect(await screen.findByText("Prism", { selector: "span" })).toBeInTheDocument();
    const trigger = screen.getByText("How Prism works");

    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Prism is a self-evolving prompt optimizer");
  });
});

describe("NewMigrationWizard", () => {
  it("disables Continue until at least one model is checked", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());

    renderWizard(vi.fn());

    await screen.findByLabelText("gpt-4o-mini");
    expect(
      screen.getByRole("button", { name: "Continue to budget & parity threshold" })
    ).toBeDisabled();
    expect(screen.getByText("Select at least one model to continue.")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("gpt-4o-mini"));

    expect(
      screen.getByRole("button", { name: "Continue to budget & parity threshold" })
    ).toBeEnabled();
  });

  it("walks through all three steps and calls onCreated with the new migration", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(createMigration).mockResolvedValue({
      id: 42,
      pipeline_id: 1,
      target_model_config: { models: ["gpt-4o-mini", "claude-haiku-4-5"] },
      budget: 25,
      parity_threshold: 0.9,
      status: "pending",
      total_cost_usd: null,
      stopped_early: false,
      stop_reason: null,
      progress_stage_name: null,
      progress_current: null,
      progress_total: null,
      progress_substep: null,
      activity_log: null,
      completed_at: null,
      stage_states: {},
    });

    const onCreated = vi.fn();
    renderWizard(onCreated);

    // Step 1: check both models
    await screen.findByLabelText("gpt-4o-mini");
    fireEvent.click(screen.getByLabelText("gpt-4o-mini"));
    fireEvent.click(screen.getByLabelText("claude-haiku-4-5"));
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to budget & parity threshold" })
    );

    // Step 2: budget + parity
    await screen.findByLabelText("Budget");
    fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("Parity threshold"), { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));

    // Step 3: confirm
    await screen.findByRole("button", { name: "Run migration" });
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("claude-haiku-4-5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run migration" }));

    await waitFor(() => {
      expect(createMigration).toHaveBeenCalledWith(1, {
        target_model_config: { models: ["gpt-4o-mini", "claude-haiku-4-5"] },
        budget: 25,
        parity_threshold: 0.9,
      });
    });

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 42 }));
    });
  });

  it("shows a validation hint and blocks continue for a non-positive budget", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());

    renderWizard(vi.fn());
    await screen.findByLabelText("gpt-4o-mini");
    fireEvent.click(screen.getByLabelText("gpt-4o-mini"));
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to budget & parity threshold" })
    );

    await screen.findByLabelText("Budget");
    fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "0" } });

    expect(screen.getByText(/Budget must be greater than \$0/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue to review" })).toBeDisabled();
  });

  it("sends a stage_overrides entry only for a stage whose per-stage selection was actually customized", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(createMigration).mockResolvedValue({
      id: 43,
      pipeline_id: 1,
      target_model_config: {
        models: ["gpt-4o-mini"],
        stage_overrides: { "11": ["claude-haiku-4-5"] },
      },
      budget: 25,
      parity_threshold: 0.9,
      status: "pending",
      total_cost_usd: null,
      stopped_early: false,
      stop_reason: null,
      progress_stage_name: null,
      progress_current: null,
      progress_total: null,
      progress_substep: null,
      activity_log: null,
      completed_at: null,
      stage_states: {},
    });

    const onCreated = vi.fn();
    renderWizard(onCreated);

    // Global selection: gpt-4o-mini only.
    await screen.findByLabelText("gpt-4o-mini");
    fireEvent.click(screen.getByLabelText("gpt-4o-mini"));

    // Open the advanced section and customize only the "Summarize" stage
    // (stage id 11) to use claude-haiku-4-5 instead of the global default.
    fireEvent.click(screen.getByRole("button", { name: "Advanced: customize per stage" }));
    await screen.findByLabelText("gpt-4o-mini for Summarize");

    // Before any customization, every stage's boxes mirror the global pick.
    expect(screen.getByLabelText("gpt-4o-mini for Extract")).toBeChecked();
    expect(screen.getByLabelText("gpt-4o-mini for Summarize")).toBeChecked();

    fireEvent.click(screen.getByLabelText("gpt-4o-mini for Summarize"));
    fireEvent.click(screen.getByLabelText("claude-haiku-4-5 for Summarize"));

    // "Extract" was never touched - still just mirrors the global default,
    // and only "Summarize" (the stage actually customized) is flagged.
    expect(screen.getByLabelText("gpt-4o-mini for Extract")).toBeChecked();
    expect(screen.getAllByText("Customized")).toHaveLength(1);

    fireEvent.click(
      screen.getByRole("button", { name: "Continue to budget & parity threshold" })
    );

    await screen.findByLabelText("Budget");
    fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText("Parity threshold"), { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));

    await screen.findByRole("button", { name: "Run migration" });
    expect(screen.getByText(/claude-haiku-4-5/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run migration" }));

    await waitFor(() => {
      expect(createMigration).toHaveBeenCalledWith(1, {
        target_model_config: {
          models: ["gpt-4o-mini"],
          stage_overrides: { "11": ["claude-haiku-4-5"] },
        },
        budget: 25,
        parity_threshold: 0.9,
      });
    });
  });

  it("drops a stage's override once its selection is changed back to match the global default", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(createMigration).mockResolvedValue({
      id: 44,
      pipeline_id: 1,
      target_model_config: { models: ["gpt-4o-mini"] },
      budget: 10,
      parity_threshold: 0.95,
      status: "pending",
      total_cost_usd: null,
      stopped_early: false,
      stop_reason: null,
      progress_stage_name: null,
      progress_current: null,
      progress_total: null,
      progress_substep: null,
      activity_log: null,
      completed_at: null,
      stage_states: {},
    });

    const onCreated = vi.fn();
    renderWizard(onCreated);

    await screen.findByLabelText("gpt-4o-mini");
    fireEvent.click(screen.getByLabelText("gpt-4o-mini"));
    fireEvent.click(screen.getByRole("button", { name: "Advanced: customize per stage" }));
    await screen.findByLabelText("claude-haiku-4-5 for Extract");

    // Customize, then revert back to exactly the global default.
    fireEvent.click(screen.getByLabelText("claude-haiku-4-5 for Extract"));
    expect(screen.getByText("Customized")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("claude-haiku-4-5 for Extract"));
    expect(screen.queryByText("Customized")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Continue to budget & parity threshold" })
    );
    await screen.findByLabelText("Budget");
    fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));
    await screen.findByRole("button", { name: "Run migration" });
    fireEvent.click(screen.getByRole("button", { name: "Run migration" }));

    await waitFor(() => {
      // Reverted back to the default - no stage_overrides key sent at all,
      // same bare shape as if Advanced had never been opened.
      expect(createMigration).toHaveBeenCalledWith(1, {
        target_model_config: { models: ["gpt-4o-mini"] },
        budget: 10,
        parity_threshold: 0.95,
      });
    });
  });

  it("blocks continuing when a customized stage is left with zero models selected", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());

    renderWizard(vi.fn());
    await screen.findByLabelText("gpt-4o-mini");
    fireEvent.click(screen.getByLabelText("gpt-4o-mini"));
    fireEvent.click(screen.getByRole("button", { name: "Advanced: customize per stage" }));
    await screen.findByLabelText("gpt-4o-mini for Extract");

    // Uncheck the only model this stage had, leaving it empty.
    fireEvent.click(screen.getByLabelText("gpt-4o-mini for Extract"));

    expect(
      screen.getByRole("button", { name: "Continue to budget & parity threshold" })
    ).toBeDisabled();
    expect(screen.getByText(/Select at least one model for Extract/)).toBeInTheDocument();
  });

  it("displays model card transform rules when available", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(getModelCard).mockImplementation((model) => {
      if (model === "gpt-4o-mini") {
        return Promise.resolve(baseModelCard("openai"));
      }
      if (model === "claude-haiku-4-5") {
        return Promise.resolve(baseModelCard("anthropic"));
      }
      return Promise.reject(new Error("Not found"));
    });

    renderWizard(vi.fn());
    await screen.findByLabelText("gpt-4o-mini");

    await waitFor(() => {
      const headings = screen.getAllByText("Model transform rules");
      expect(headings.length).toBeGreaterThan(0);
    });

    const rules = screen.getAllByText(/test_rule/);
    expect(rules.length).toBeGreaterThanOrEqual(1);
    const descriptions = screen.getAllByText(/A test rule/);
    expect(descriptions.length).toBeGreaterThanOrEqual(1);
  });

  it("explains why a non-applying transform rule doesn't apply, instead of just striking it through", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(getModelCard).mockResolvedValue({
      ...baseModelCard("openai"),
      rules: [
        {
          name: "terseify_if_small",
          description: "Strip hedging/filler phrases.",
          applies_to: "small_only",
          will_apply: false,
        },
      ],
    });

    renderWizard(vi.fn());
    await screen.findByLabelText("gpt-4o-mini");

    const explanations = await screen.findAllByText(
      /only applies to small\/cheap model variants/
    );
    expect(explanations.length).toBeGreaterThanOrEqual(1);
  });

  it("shows key-requiring models locked (visible but disabled) when their provider has no key", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(getModelCard).mockRejectedValue(new Error("skip"));
    // Only openai has a key - the anthropic model should be locked.
    vi.mocked(listApiKeys).mockResolvedValue([keyFor("openai")]);

    renderWizard(vi.fn());

    const anthropicCheckbox = await screen.findByLabelText("claude-haiku-4-5");
    await waitFor(() => expect(anthropicCheckbox).toBeDisabled());
    expect(screen.getByLabelText("gpt-4o-mini")).toBeEnabled();
    // Locked models stay discoverable, with an inline unlock affordance.
    expect(screen.getByText("API key required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add API key" })).toBeInTheDocument();
  });

  it("never locks models that require no API key, even with zero keys configured", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue([
      {
        ...baseModels()[0],
        model: "ollama/llama3.1",
        provider: "ollama",
        requires_api_key: false,
      },
    ]);
    vi.mocked(getModelCard).mockRejectedValue(new Error("skip"));
    vi.mocked(listApiKeys).mockResolvedValue([]);

    renderWizard(vi.fn());

    expect(await screen.findByLabelText("ollama/llama3.1")).toBeEnabled();
    expect(screen.queryByText("API key required")).not.toBeInTheDocument();
  });

  it("adds a key inline and unlocks the model without leaving the wizard", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(getModelCard).mockRejectedValue(new Error("skip"));
    // First fetch: no anthropic key. After the add succeeds and the query is
    // invalidated, the refetch returns the new key - unlocking the model.
    vi.mocked(listApiKeys)
      .mockResolvedValueOnce([keyFor("openai")])
      .mockResolvedValue([keyFor("openai", 1), keyFor("anthropic", 2)]);
    vi.mocked(addApiKey).mockResolvedValue(keyFor("anthropic", 2));

    renderWizard(vi.fn());

    const anthropicCheckbox = await screen.findByLabelText("claude-haiku-4-5");
    await waitFor(() => expect(anthropicCheckbox).toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Add API key" }));
    // The drawer portals outside the render root - query via document.
    const keyInput = await screen.findByLabelText("API key");
    fireEvent.change(keyInput, { target: { value: "sk-ant-test-key-000000000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key & unlock models" }));

    await waitFor(() => {
      expect(addApiKey).toHaveBeenCalledWith("anthropic", "sk-ant-test-key-000000000000");
    });
    // Invalidation refetches the keys and the model unlocks in place.
    await waitFor(() => expect(screen.getByLabelText("claude-haiku-4-5")).toBeEnabled());
    fireEvent.click(screen.getByLabelText("claude-haiku-4-5"));
    expect(screen.getByLabelText("claude-haiku-4-5")).toBeChecked();
  });

  it("searches the OpenRouter catalog and adds a selected model", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());
    vi.mocked(getModelCard).mockRejectedValue(new Error("skip"));
    vi.mocked(listOpenRouterCatalog).mockResolvedValue([
      {
        model: "openrouter/anthropic/claude-3.7-sonnet",
        provider: "openrouter",
        input_cost_per_1m: 3,
        output_cost_per_1m: 15,
        max_input_tokens: 200000,
        max_output_tokens: 64000,
        supports_json_mode: true,
        supports_function_calling: true,
        requires_api_key: true,
        family: "anthropic",
        transform_descriptions: [],
      },
      {
        model: "openrouter/openai/gpt-4o",
        provider: "openrouter",
        input_cost_per_1m: 2.5,
        output_cost_per_1m: 10,
        max_input_tokens: 128000,
        max_output_tokens: 16384,
        supports_json_mode: true,
        supports_function_calling: true,
        requires_api_key: true,
        family: "openai",
        transform_descriptions: [],
      },
    ]);

    renderWizard(vi.fn());

    await screen.findByLabelText("gpt-4o-mini");
    const search = await screen.findByLabelText("Search OpenRouter models");
    await waitFor(() => expect(search).not.toBeDisabled());

    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: "claude" } });

    const result = await screen.findByRole("option", {
      name: "openrouter/anthropic/claude-3.7-sonnet",
    });
    expect(
      screen.queryByRole("option", { name: "openrouter/openai/gpt-4o" })
    ).not.toBeInTheDocument();

    fireEvent.click(result);

    expect(await screen.findByLabelText("openrouter/anthropic/claude-3.7-sonnet")).toBeInTheDocument();
    expect(search).toHaveValue("");
  });
});
