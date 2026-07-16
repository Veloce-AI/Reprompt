import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import PipelineWorkspace, { type WorkspaceTab } from "./pipeline-workspace";
import type { DagResponse, MigrationOut, PipelineSummary, StageRunState } from "@/lib/api";

// This suite is specifically about the Canvas tab's live-migration overlay
// (DEV_TRACKER.md "Canvas tab live migration overlay") - whether
// stageStates/runningSubstep actually reach <PipelineCanvas> when a
// migration is running in the background, and that nothing extra is fetched
// or rendered when one isn't. The main pipeline-workspace.test.tsx suite
// stubs PipelineCanvas down to a bare button since it only cares about
// tab/drawer wiring - this file's stub instead echoes the live props back
// out as text so they're assertable.
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listPipelines: vi.fn(),
    getPipelineDag: vi.fn(),
    listMigrations: vi.fn(),
    getMigrationStatus: vi.fn(),
    // Not exercised by this suite (it's about the Canvas tab), but the
    // "parked on a non-canvas tab" test switches to the Data tab, which
    // mounts the real (unmocked) <DataTable> - stub this so that doesn't
    // hit the real network layer.
    listStageRecords: vi.fn(),
  };
});

vi.mock("@/components/pipeline-canvas", () => ({
  PipelineCanvas: ({
    stageStates,
    runningSubstep,
  }: {
    stageStates?: Record<string, StageRunState>;
    runningSubstep?: string | null;
  }) => (
    <div data-testid="mock-canvas">
      <span data-testid="stage-states">{JSON.stringify(stageStates ?? null)}</span>
      <span data-testid="running-substep">{runningSubstep ?? "none"}</span>
    </div>
  ),
}));

import { getMigrationStatus, getPipelineDag, listMigrations, listPipelines } from "@/lib/api";

window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

function basePipeline(): PipelineSummary {
  return {
    id: 1,
    name: "Live Canvas Test Pipeline",
    stage_count: 1,
    models_used: ["gpt-4o"],
    benchmark_query_count: 1,
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

function makeMigration(overrides: Partial<MigrationOut> = {}): MigrationOut {
  return {
    id: 9,
    pipeline_id: 1,
    target_model_config: { models: ["gpt-4o-mini"] },
    budget: 10,
    parity_threshold: 0.95,
    status: "running",
    total_cost_usd: null,
    stopped_early: false,
    stop_reason: null,
    progress_stage_name: "Extract",
    progress_current: 1,
    progress_total: 1,
    progress_substep: "refining",
    activity_log: null,
    completed_at: null,
    stage_states: { "10": "running" },
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

  const routeTree = rootRoute.addChildren([pipelineWorkspaceRoute]);

  return createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
}

function renderAt(initialPath: string) {
  const router = buildRouter(initialPath);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(listPipelines).mockReset();
  vi.mocked(getPipelineDag).mockReset();
  vi.mocked(listMigrations).mockReset();
  vi.mocked(getMigrationStatus).mockReset();

  vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);
  vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
});

describe("PipelineWorkspace — Canvas tab live migration overlay", () => {
  it("stays static (no stageStates, no badge, no status poll) when no migration is running", async () => {
    vi.mocked(listMigrations).mockResolvedValue([makeMigration({ status: "completed" })]);

    renderAt("/pipelines/1");

    await screen.findByTestId("mock-canvas");
    await waitFor(() => {
      expect(listMigrations).toHaveBeenCalledWith(1);
    });

    expect(screen.getByTestId("stage-states")).toHaveTextContent("null");
    expect(screen.getByTestId("running-substep")).toHaveTextContent("none");
    expect(screen.queryByText(/Migration running/)).not.toBeInTheDocument();
    expect(getMigrationStatus).not.toHaveBeenCalled();
  });

  it("colors the canvas live and shows the running badge when a migration is running", async () => {
    vi.mocked(listMigrations).mockResolvedValue([makeMigration()]);
    vi.mocked(getMigrationStatus).mockResolvedValue(makeMigration());

    renderAt("/pipelines/1");

    await waitFor(() => {
      expect(screen.getByTestId("stage-states")).toHaveTextContent('{"10":"running"}');
    });
    expect(screen.getByTestId("running-substep")).toHaveTextContent("refining");
    expect(screen.getByText(/Migration running/)).toBeInTheDocument();
    expect(getMigrationStatus).toHaveBeenCalledWith(1, 9);
  });

  it("does not poll or color the canvas while parked on a non-canvas tab", async () => {
    vi.mocked(listMigrations).mockResolvedValue([makeMigration()]);
    vi.mocked(getMigrationStatus).mockResolvedValue(makeMigration());

    renderAt("/pipelines/1?tab=data");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Data" })).toHaveAttribute("aria-current", "page");
    });

    expect(screen.queryByTestId("mock-canvas")).not.toBeInTheDocument();
    expect(getMigrationStatus).not.toHaveBeenCalled();
  });

  it("jumps to the Migrations tab when the running badge is clicked", async () => {
    vi.mocked(listMigrations).mockResolvedValue([makeMigration()]);
    vi.mocked(getMigrationStatus).mockResolvedValue(makeMigration());

    renderAt("/pipelines/1");

    const badge = await screen.findByText(/Migration running/);
    fireEvent.click(badge);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Migrations" })).toHaveAttribute("aria-current", "page");
    });
  });
});
