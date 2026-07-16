import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MigrationSuccessScreen } from "./migration-success-screen";
import type { ActivityLogEntry, DagResponse, MigrationOut } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getMigrationStatus: vi.fn(),
    getPipelineDag: vi.fn(),
    startMigration: vi.fn(),
  };
});

// Same convention as pipeline-workspace.test.tsx: React Flow needs browser
// APIs jsdom doesn't provide, and this suite is about the activity log /
// reasoning drawer wiring, not React Flow's own rendering — stub with plain
// buttons that fire onNodeClick like real node clicks would, one per stage
// id used across these tests.
vi.mock("@/components/pipeline-canvas", () => ({
  PipelineCanvas: ({ onNodeClick }: { onNodeClick?: (stageId: number) => void }) => (
    <div>
      <button onClick={() => onNodeClick?.(10)}>mock-node-10</button>
      <button onClick={() => onNodeClick?.(20)}>mock-node-20</button>
    </div>
  ),
}));

import { getMigrationStatus, getPipelineDag } from "@/lib/api";

function baseDag(): DagResponse {
  return {
    pipeline_id: 1,
    layers: [{ stage_ids: [10, 20] }],
    stages: {
      "10": { id: 10, name: "Extract", model: "gpt-4o", avg_tokens_in: 100, avg_tokens_out: 50, avg_latency_ms: 500 },
      "20": { id: 20, name: "Summarize", model: "gpt-4o", avg_tokens_in: 80, avg_tokens_out: 40, avg_latency_ms: 400 },
    },
    edges: [],
  };
}

function baseActivityLog(): ActivityLogEntry[] {
  return [
    { stage_id: 10, phase: "mutating", detail: null, timestamp: "2026-07-16T09:00:00Z" },
    { stage_id: 10, phase: "refining", detail: "needs work", timestamp: "2026-07-16T09:00:05Z" },
    { stage_id: 20, phase: "sweeping", detail: null, timestamp: "2026-07-16T09:00:10Z" },
  ];
}

function baseMigration(overrides: Partial<MigrationOut> = {}): MigrationOut {
  return {
    id: 5,
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
    progress_total: 2,
    progress_substep: "refining",
    activity_log: baseActivityLog(),
    completed_at: null,
    stage_states: { "10": "running", "20": "done" },
    ...overrides,
  };
}

function renderScreen(migration: MigrationOut) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MigrationSuccessScreen migration={migration} pipelineId="1" onBackToCanvas={vi.fn()} />
    </QueryClientProvider>
  );
}

describe("MigrationSuccessScreen — activity log + live reasoning feed", () => {
  it("renders the activity log with stage names and detail/phase labels, newest at the bottom", async () => {
    vi.mocked(getMigrationStatus).mockResolvedValue(baseMigration());
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());

    renderScreen(baseMigration());

    // Wait for the DAG query to resolve (stage names) before reading lines -
    // the log renders immediately off the status poll, falling back to
    // "Stage {id}" until the DAG's real names arrive. Checked via the real
    // DOM textContent (recursive) rather than RTL's findByText, which only
    // matches an element's *direct* text-node children and would never
    // match text split across the "<span>{name}</span>: {detail}" markup.
    const log = await screen.findByRole("log");
    await waitFor(() => expect(log.textContent).toContain("Extract: Generating prompt variants"));

    const lines = Array.from(log.querySelectorAll("p")).map((p) => p.textContent);

    expect(lines).toEqual([
      "Extract: Generating prompt variants",
      "Extract: needs work",
      "Summarize: Running parameter sweep",
    ]);
  });

  it("opens the reasoning drawer with the latest critique text when a running stage node is clicked", async () => {
    vi.mocked(getMigrationStatus).mockResolvedValue(baseMigration());
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());

    renderScreen(baseMigration());

    await waitFor(() => expect(screen.getByText("mock-node-10")).toBeInTheDocument());
    fireEvent.click(screen.getByText("mock-node-10"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Extract")).toBeInTheDocument();
    expect(within(dialog).getByText("Refining prompt")).toBeInTheDocument();
    expect(within(dialog).getByText("needs work")).toBeInTheDocument();
  });

  it("does not open the reasoning drawer when a non-running stage node is clicked", async () => {
    vi.mocked(getMigrationStatus).mockResolvedValue(baseMigration());
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());

    renderScreen(baseMigration());

    // Let the status/DAG queries settle before clicking, so the click
    // itself is the only state update left to observe.
    const log = await screen.findByRole("log");
    await waitFor(() => expect(log.textContent).toContain("Summarize: Running parameter sweep"));

    fireEvent.click(screen.getByText("mock-node-20"));

    // A non-running node click is a no-op here - the drawer never opens.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
