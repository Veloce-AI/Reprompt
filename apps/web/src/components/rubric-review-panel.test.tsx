import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RubricReviewPanel } from "./rubric-review-panel";
import type { RubricOut } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  listRubrics: vi.fn(),
  updateRubric: vi.fn(),
  approveRubric: vi.fn(),
  approveAllRubrics: vi.fn(),
  getPipelineDag: vi.fn(),
  generateRubric: vi.fn(),
  listConfiguredModels: vi.fn(),
}));

import {
  approveAllRubrics,
  approveRubric,
  generateRubric,
  getPipelineDag,
  listConfiguredModels,
  listRubrics,
  updateRubric,
} from "@/lib/api";

function baseRubric(overrides: Partial<RubricOut> = {}): RubricOut {
  return {
    id: 1,
    stage_id: 10,
    stage_name: "Extract financials",
    deterministic_checks: [
      { type: "required_keys", id: "req-1", keys: ["currency", "revenue"] },
      { type: "length_bounds", id: "len-1", min_length: 20, max_length: 800, unit: "chars" },
    ],
    judge_criteria: [
      {
        name: "Covers all key entities",
        weight: 0.6,
        description: "Mentions every product/customer name that appeared in the input.",
      },
    ],
    downstream_contract: ["currency", "revenue"],
    approved: false,
    ...overrides,
  };
}

function renderPanel(pipelineId = 1) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RubricReviewPanel pipelineId={pipelineId} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listRubrics).mockReset();
  vi.mocked(updateRubric).mockReset();
  vi.mocked(approveRubric).mockReset();
  vi.mocked(approveAllRubrics).mockReset();
  vi.mocked(generateRubric).mockReset();
  vi.mocked(getPipelineDag).mockReset();
  vi.mocked(getPipelineDag).mockResolvedValue({
    pipeline_id: 1,
    layers: [],
    stages: {},
    edges: [],
  });
  vi.mocked(listConfiguredModels).mockReset();
  vi.mocked(listConfiguredModels).mockResolvedValue([]);
});

describe("RubricReviewPanel", () => {
  it("renders plain-English sentences for each check, never the raw check type", async () => {
    vi.mocked(listRubrics).mockResolvedValue([baseRubric()]);

    renderPanel();

    await screen.findByText("Extract financials");
    expect(screen.getByText("Must include: currency, revenue")).toBeInTheDocument();
    expect(
      screen.getByText("Length must be between 20 and 800 characters")
    ).toBeInTheDocument();
    expect(screen.getByText(/Covers all key entities/)).toBeInTheDocument();
    expect(screen.getByText("Next stage reads: currency")).toBeInTheDocument();

    expect(screen.queryByText("required_keys")).not.toBeInTheDocument();
    expect(screen.queryByText(/json schema/i)).not.toBeInTheDocument();
  });

  it("groups items into Format checks / Content criteria / Downstream contract", async () => {
    vi.mocked(listRubrics).mockResolvedValue([baseRubric()]);

    renderPanel();

    await screen.findByText("Extract financials");
    expect(screen.getByText("Format checks")).toBeInTheDocument();
    expect(screen.getByText("Content criteria")).toBeInTheDocument();
    expect(screen.getByText("Downstream contract")).toBeInTheDocument();
  });

  it("renders each stage card with an id anchor for the canvas drawer's deep link", async () => {
    vi.mocked(listRubrics).mockResolvedValue([baseRubric()]);

    renderPanel();

    await screen.findByText("Extract financials");
    expect(document.getElementById("rubric-10")).toBeInTheDocument();
  });

  it("deletes a format check and PATCHes the remaining list", async () => {
    const rubric = baseRubric();
    vi.mocked(listRubrics).mockResolvedValue([rubric]);
    vi.mocked(updateRubric).mockImplementation(async (_id, patch) => ({ ...rubric, ...patch }));

    renderPanel();
    await screen.findByText("Must include: currency, revenue");

    const requiredKeysRow = screen.getByText("Must include: currency, revenue").closest("li")!;
    fireEvent.click(within(requiredKeysRow).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(updateRubric).toHaveBeenCalledWith(1, {
        deterministic_checks: [
          { type: "length_bounds", id: "len-1", min_length: 20, max_length: 800, unit: "chars" },
        ],
      });
    });

    await waitFor(() => {
      expect(screen.queryByText("Must include: currency, revenue")).not.toBeInTheDocument();
    });
  });

  it("approves a single stage and reflects the approved badge", async () => {
    const rubric = baseRubric();
    vi.mocked(listRubrics).mockResolvedValue([rubric]);
    vi.mocked(approveRubric).mockResolvedValue({ ...rubric, approved: true });

    renderPanel();
    await screen.findByText("Needs review");

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(approveRubric).toHaveBeenCalledWith(1);
    });
    expect(await screen.findAllByText("Approved")).not.toHaveLength(0);
  });

  it("approves all stages via the Approve all button", async () => {
    const rubricA = baseRubric({ id: 1, stage_id: 10, stage_name: "Extract" });
    const rubricB = baseRubric({ id: 2, stage_id: 11, stage_name: "Summarize" });
    vi.mocked(listRubrics).mockResolvedValue([rubricA, rubricB]);
    vi.mocked(approveAllRubrics).mockResolvedValue([
      { ...rubricA, approved: true },
      { ...rubricB, approved: true },
    ]);

    renderPanel();
    await screen.findByText("Extract");
    await screen.findByText("Summarize");

    fireEvent.click(screen.getByRole("button", { name: "Approve all" }));

    await waitFor(() => {
      expect(approveAllRubrics).toHaveBeenCalledWith(1);
    });
    await screen.findByRole("button", { name: "All stages approved" });
    expect(screen.getByRole("button", { name: "All stages approved" })).toBeDisabled();
  });

  it("shows an empty state when the pipeline has no rubrics yet", async () => {
    vi.mocked(listRubrics).mockResolvedValue([]);

    renderPanel();

    expect(await screen.findByText("No rubrics yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve all" })).not.toBeInTheDocument();
  });

  it("offers a dropdown of unlocked models instead of requiring a typed-in string", async () => {
    vi.mocked(listRubrics).mockResolvedValue([]);
    vi.mocked(listConfiguredModels).mockResolvedValue([
      {
        model: "gpt-4o",
        provider: "openai",
        input_cost_per_1m: 2.5,
        output_cost_per_1m: 10,
        max_input_tokens: 128000,
        max_output_tokens: 16384,
        supports_json_mode: true,
        supports_function_calling: true,
        requires_api_key: true,
        unlocked: true,
        model_card: {
          family: "openai",
          version: 1,
          description: "",
          is_small_variant: false,
          rules: [],
          supports_reasoning: false,
          code_sample: "",
        },
      },
      {
        // Locked models must not appear as choosable options.
        model: "openrouter/z-ai/glm-4.7",
        provider: "openrouter",
        input_cost_per_1m: 0.4,
        output_cost_per_1m: 1.5,
        max_input_tokens: 202752,
        max_output_tokens: 8192,
        supports_json_mode: true,
        supports_function_calling: false,
        requires_api_key: true,
        unlocked: false,
        model_card: {
          family: "generic",
          version: 1,
          description: "",
          is_small_variant: false,
          rules: [],
          supports_reasoning: false,
          code_sample: "",
        },
      },
    ]);

    renderPanel();

    const select = await screen.findByLabelText(
      "Model for rubric generation (optional — auto-selected if left blank)"
    );
    expect(within(select).getByRole("option", { name: "Auto-select a model" })).toBeInTheDocument();
    expect(await within(select).findByRole("option", { name: "gpt-4o" })).toBeInTheDocument();
    expect(
      within(select).queryByRole("option", { name: "openrouter/z-ai/glm-4.7" })
    ).not.toBeInTheDocument();
  });

  it("generates rubrics with a blank model field — auto-selection is the default, not a blocker", async () => {
    vi.mocked(listRubrics).mockResolvedValue([]);
    vi.mocked(getPipelineDag).mockResolvedValue({
      pipeline_id: 1,
      layers: [],
      stages: {
        "10": {
          id: 10,
          name: "Extract",
          model: "gpt-4o",
          avg_tokens_in: null,
          avg_tokens_out: null,
          avg_latency_ms: null,
          trace_count: 0,
          total_cost_usd: null,
        },
      },
      edges: [],
    });
    vi.mocked(generateRubric).mockResolvedValue(baseRubric({ generated_with_model: "claude-sonnet-4-5" }));

    renderPanel();
    await screen.findByText("No rubrics yet");

    // No text typed into the model field at all.
    fireEvent.click(screen.getByRole("button", { name: "Generate all rubrics" }));

    await waitFor(() => {
      expect(generateRubric).toHaveBeenCalledWith(1, 10, undefined);
    });
  });

  it("shows a 'generated using <model>' caption after a rubric is generated", async () => {
    const rubric = baseRubric({ generated_with_model: "claude-sonnet-4-5" });
    vi.mocked(listRubrics).mockResolvedValue([rubric]);

    renderPanel();

    expect(await screen.findByText(/generated using claude-sonnet-4-5/i)).toBeInTheDocument();
  });

  it("does not show a 'generated using' caption when the rubric wasn't just generated", async () => {
    vi.mocked(listRubrics).mockResolvedValue([baseRubric()]);

    renderPanel();
    await screen.findByText("Extract financials");

    expect(screen.queryByText(/generated using/i)).not.toBeInTheDocument();
  });

  it("the Regenerate button is enabled even with a blank model field", async () => {
    vi.mocked(listRubrics).mockResolvedValue([baseRubric()]);

    renderPanel();
    await screen.findByText("Extract financials");

    expect(screen.getByRole("button", { name: "Regenerate" })).not.toBeDisabled();
  });
});
