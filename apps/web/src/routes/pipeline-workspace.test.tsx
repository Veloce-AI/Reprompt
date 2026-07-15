import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
  RouterProvider,
} from "@tanstack/react-router";
import PipelineWorkspace, { type WorkspaceTab } from "./pipeline-workspace";
import type { DagResponse, MigrationOut, PipelineSummary, RubricOut } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listPipelines: vi.fn(),
    updatePipeline: vi.fn(),
    getPipelineDag: vi.fn(),
    listRubrics: vi.fn(),
    approveRubric: vi.fn(),
    approveAllRubrics: vi.fn(),
    generateRubric: vi.fn(),
    listMigrations: vi.fn(),
    listModelOptions: vi.fn(),
    getModelCard: vi.fn(),
    createMigration: vi.fn(),
  };
});

// The canvas tab's real <PipelineCanvas> renders @xyflow/react, which needs
// browser APIs (ResizeObserver etc.) jsdom doesn't provide - this suite is
// about the workspace's tab/drawer/redirect wiring, not React Flow's own
// rendering (untested here, same as every other route test in this repo),
// so stub it with a plain button that fires onNodeClick like a real node
// click would.
vi.mock("@/components/pipeline-canvas", () => ({
  PipelineCanvas: ({ onNodeClick }: { onNodeClick?: (stageId: number) => void }) => (
    <button onClick={() => onNodeClick?.(10)}>mock-node-10</button>
  ),
}));

import {
  approveRubric,
  getPipelineDag,
  listMigrations,
  listModelOptions,
  listPipelines,
  listRubrics,
  updatePipeline,
} from "@/lib/api";

window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
// jsdom doesn't implement scrollIntoView - the rubrics tab's deep-link
// effect (see rubric-review-panel.tsx) calls it once a hash is set.
Element.prototype.scrollIntoView = vi.fn();

function basePipeline(overrides: Partial<PipelineSummary> = {}): PipelineSummary {
  return {
    id: 1,
    name: "Diamond Test Pipeline",
    stage_count: 1,
    models_used: ["gpt-4o"],
    benchmark_query_count: 1,
    ...overrides,
  };
}

function baseDag(): DagResponse {
  return {
    pipeline_id: 1,
    layers: [{ stage_ids: [10] }],
    stages: {
      "10": {
        id: 10,
        name: "Extract",
        model: "gpt-4o",
        avg_tokens_in: 100,
        avg_tokens_out: 50,
        avg_latency_ms: 500,
      },
    },
    edges: [],
  };
}

function baseRubric(overrides: Partial<RubricOut> = {}): RubricOut {
  return {
    id: 1,
    stage_id: 10,
    stage_name: "Extract",
    deterministic_checks: [],
    judge_criteria: [],
    downstream_contract: [],
    approved: false,
    ...overrides,
  };
}

function buildRouter(initialPath: string) {
  const rootRoute = createRootRoute();

  function validateWorkspaceSearch(search: Record<string, unknown>): { tab: WorkspaceTab } {
    const raw = typeof search.tab === "string" ? search.tab : undefined;
    const allowed: WorkspaceTab[] = ["canvas", "data", "rubrics", "migrations"];
    return { tab: allowed.includes(raw as WorkspaceTab) ? (raw as WorkspaceTab) : "canvas" };
  }

  const pipelineWorkspaceRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines/$pipelineId",
    validateSearch: validateWorkspaceSearch,
    component: PipelineWorkspace,
  });

  const rubricReviewRedirectRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines/$pipelineId/rubrics",
    beforeLoad: ({ params }) => {
      throw redirect({ to: "/pipelines/$pipelineId", params, search: { tab: "rubrics" } });
    },
  });

  const newMigrationRedirectRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines/$pipelineId/migrations/new",
    beforeLoad: ({ params }) => {
      throw redirect({ to: "/pipelines/$pipelineId", params, search: { tab: "migrations" } });
    },
  });

  const routeTree = rootRoute.addChildren([
    pipelineWorkspaceRoute,
    rubricReviewRedirectRoute,
    newMigrationRedirectRoute,
  ]);

  return createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
}

function renderAt(initialPath: string) {
  const router = buildRouter(initialPath);
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
  vi.mocked(listPipelines).mockReset();
  vi.mocked(updatePipeline).mockReset();
  vi.mocked(getPipelineDag).mockReset();
  vi.mocked(listRubrics).mockReset();
  vi.mocked(approveRubric).mockReset();
  vi.mocked(listMigrations).mockReset();
  vi.mocked(listModelOptions).mockReset();
  window.location.hash = "";

  vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);
  vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
});

describe("PipelineWorkspace", () => {
  it("defaults to the canvas tab and renders the pipeline canvas", async () => {
    renderAt("/pipelines/1");

    expect(await screen.findByText("mock-node-10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Canvas" })).toHaveAttribute("aria-current", "page");
  });

  it("switches to the rubrics tab when its tab button is clicked", async () => {
    vi.mocked(listRubrics).mockResolvedValue([]);

    renderAt("/pipelines/1");
    await screen.findByText("mock-node-10");

    fireEvent.click(screen.getByRole("button", { name: "Rubrics" }));

    expect(await screen.findByText("No rubrics yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rubrics" })).toHaveAttribute("aria-current", "page");
  });

  it("redirects the old /rubrics route into the workspace's rubrics tab", async () => {
    vi.mocked(listRubrics).mockResolvedValue([]);

    renderAt("/pipelines/1/rubrics");

    expect(await screen.findByText("No rubrics yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rubrics" })).toHaveAttribute("aria-current", "page");
  });

  it("redirects the old /migrations/new route into the workspace's migrations tab", async () => {
    vi.mocked(listMigrations).mockResolvedValue([]);
    vi.mocked(listModelOptions).mockResolvedValue([]);

    renderAt("/pipelines/1/migrations/new");

    expect(await screen.findByText("Target models")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Migrations" })).toHaveAttribute("aria-current", "page");
  });

  it("shows an existing migration's success screen instead of the wizard when one already exists", async () => {
    const migration: MigrationOut = {
      id: 7,
      pipeline_id: 1,
      target_model_config: { models: ["gpt-4o-mini"] },
      budget: 10,
      parity_threshold: 0.9,
      status: "pending",
      total_cost_usd: null,
      stopped_early: false,
      stop_reason: null,
      progress_stage_name: null,
      progress_current: null,
      progress_total: null,
      progress_substep: null,
      completed_at: null,
      stage_states: {},
    };
    vi.mocked(listMigrations).mockResolvedValue([migration]);

    renderAt("/pipelines/1/migrations/new");

    expect(await screen.findByText("Migration #7 created")).toBeInTheDocument();
  });

  it("opens the stage rubric drawer on node click and lets the reviewer approve from it", async () => {
    const rubric = baseRubric();
    vi.mocked(listRubrics).mockResolvedValue([rubric]);
    vi.mocked(approveRubric).mockResolvedValue({ ...rubric, approved: true });

    renderAt("/pipelines/1");
    await screen.findByText("mock-node-10");

    fireEvent.click(screen.getByText("mock-node-10"));

    expect(await screen.findByText("Stage id 10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(approveRubric).toHaveBeenCalledWith(1);
    });
  });

  it("switches to the rubrics tab and sets the hash when 'View full rubric' is clicked", async () => {
    const rubric = baseRubric();
    vi.mocked(listRubrics).mockResolvedValue([rubric]);

    renderAt("/pipelines/1");
    await screen.findByText("mock-node-10");
    fireEvent.click(screen.getByText("mock-node-10"));

    const link = await screen.findByRole("button", { name: "View full rubric →" });
    fireEvent.click(link);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Rubrics" })).toHaveAttribute("aria-current", "page");
    });
    expect(window.location.hash).toBe("#rubric-10");
  });

  it("saves a renamed pipeline via inline edit", async () => {
    vi.mocked(updatePipeline).mockResolvedValue(basePipeline({ name: "Renamed Pipeline" }));

    renderAt("/pipelines/1");
    const nameButton = await screen.findByRole("button", { name: "Diamond Test Pipeline" });
    fireEvent.click(nameButton);

    const input = screen.getByLabelText("Pipeline name");
    fireEvent.change(input, { target: { value: "Renamed Pipeline" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(updatePipeline).toHaveBeenCalledWith(1, { name: "Renamed Pipeline" });
    });
    expect(await screen.findByRole("button", { name: "Renamed Pipeline" })).toBeInTheDocument();
  });
});
