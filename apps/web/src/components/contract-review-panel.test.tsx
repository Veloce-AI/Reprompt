import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ContractReviewPanel } from "./contract-review-panel";
import type { DagResponse } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getPipelineDag: vi.fn(),
    listAssertions: vi.fn(),
    mineContract: vi.fn(),
  };
});

import { getPipelineDag, listAssertions, mineContract } from "@/lib/api";

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
        trace_count: 3,
        total_cost_usd: 0.01,
      },
    },
    edges: [],
  };
}

function twoStageDag(): DagResponse {
  return {
    pipeline_id: 1,
    layers: [{ stage_ids: [10] }, { stage_ids: [11] }],
    stages: {
      "11": {
        id: 11,
        name: "Summarize",
        model: "gpt-4o",
        avg_tokens_in: 80,
        avg_tokens_out: 40,
        avg_latency_ms: 400,
        trace_count: 3,
        total_cost_usd: 0.01,
      },
      "10": {
        id: 10,
        name: "Extract",
        model: "gpt-4o",
        avg_tokens_in: 100,
        avg_tokens_out: 50,
        avg_latency_ms: 500,
        trace_count: 3,
        total_cost_usd: 0.01,
      },
    },
    edges: [],
  };
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContractReviewPanel pipelineId={1} />
    </QueryClientProvider>
  );
}

describe("ContractReviewPanel — 'Contract Mining' heading + explainer", () => {
  it("renders the heading with an info affordance that explains what mining does in plain language", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listAssertions).mockResolvedValue([]);

    renderPanel();

    expect(await screen.findByText("Contract Mining")).toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: "What is contract mining?" });
    fireEvent.click(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("finds what never changes across them");
    expect(tooltip).toHaveTextContent("executable contract a migrated prompt must satisfy");
  });

  it("shows the heading and info affordance even before stages load (loading state)", () => {
    vi.mocked(getPipelineDag).mockReturnValue(new Promise(() => {})); // never resolves

    renderPanel();

    expect(screen.getByText("Contract Mining")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What is contract mining?" })).toBeInTheDocument();
  });

  it("shows the heading and info affordance in the no-stages empty state", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue({ ...baseDag(), stages: {} });

    renderPanel();

    expect(await screen.findByText("No stages found — import a pipeline first.")).toBeInTheDocument();
    expect(screen.getByText("Contract Mining")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What is contract mining?" })).toBeInTheDocument();
  });

  it("mines every stage, in pipeline order, when 'Mine all' is clicked", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(twoStageDag());
    vi.mocked(listAssertions).mockResolvedValue([]);
    const minedOrder: number[] = [];
    vi.mocked(mineContract).mockImplementation(async (_pipelineId, stageId) => {
      minedOrder.push(stageId);
      return [];
    });

    renderPanel();

    expect(await screen.findByText("Extract")).toBeInTheDocument();
    expect(screen.getByText("Summarize")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mine all" }));

    await waitFor(() => {
      expect(mineContract).toHaveBeenCalledTimes(2);
    });
    expect(mineContract).toHaveBeenNthCalledWith(1, 1, 10);
    expect(mineContract).toHaveBeenNthCalledWith(2, 1, 11);
    expect(minedOrder).toEqual([10, 11]);
  });

  it("does not show 'Mine all' when there's only one stage", async () => {
    vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
    vi.mocked(listAssertions).mockResolvedValue([]);

    renderPanel();

    expect(await screen.findByText("Extract")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mine all" })).not.toBeInTheDocument();
  });
});
