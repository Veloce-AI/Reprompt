import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import NewMigration from "./new-migration";
import type { DagResponse, ModelOption, ModelCardInfo } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getPipelineDag: vi.fn(),
    listModelOptions: vi.fn(),
    createMigration: vi.fn(),
    getModelCard: vi.fn(),
  };
});

import { createMigration, getPipelineDag, listModelOptions, getModelCard } from "@/lib/api";

// TanStack Router's scroll restoration calls window.scrollTo, which jsdom
// doesn't implement - stub it out (same pattern as rubric-review.test.tsx).
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

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
      },
      "11": {
        id: 11,
        name: "Summarize",
        model: "gpt-4o",
        avg_tokens_in: 200,
        avg_tokens_out: 80,
        avg_latency_ms: 700,
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
    },
  ];
}

function renderAtPipeline(pipelineId: string) {
  const rootRoute = createRootRoute();
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines/$pipelineId/migrations/new",
    component: NewMigration,
  });
  const routeTree = rootRoute.addChildren([route]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({
      initialEntries: [`/pipelines/${pipelineId}/migrations/new`],
    }),
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
  vi.mocked(getPipelineDag).mockReset();
  vi.mocked(listModelOptions).mockReset();
  vi.mocked(createMigration).mockReset();
  vi.mocked(getModelCard).mockReset();
});

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
  };
}

describe("NewMigration wizard", () => {
  it("disables Continue until at least one model is checked", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());

    renderAtPipeline("1");

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

  it("walks through all three steps and creates a migration with multi-model config", async () => {
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
      completed_at: null,
      stage_states: {},
    });

    renderAtPipeline("1");

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

    await screen.findByText(/Migration #42 created/);
  });

  it("shows a validation hint and blocks continue for a non-positive budget", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listModelOptions).mockResolvedValue(baseModels());

    renderAtPipeline("1");
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

    renderAtPipeline("1");
    await screen.findByLabelText("gpt-4o-mini");

    // Wait for model card to fetch and display (should have at least one heading)
    await waitFor(() => {
      const headings = screen.getAllByText("Model transform rules");
      expect(headings.length).toBeGreaterThan(0);
    });

    // Verify the rule is displayed (both models should show the rule)
    const rules = screen.getAllByText(/test_rule/);
    expect(rules.length).toBeGreaterThanOrEqual(1);
    const descriptions = screen.getAllByText(/A test rule/);
    expect(descriptions.length).toBeGreaterThanOrEqual(1);
  });
});
