import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ContractReviewPanel } from "./contract-review-panel";
import type { DagResponse } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getPipelineDag: vi.fn(),
    listAssertions: vi.fn(),
  };
});

import { getPipelineDag, listAssertions } from "@/lib/api";

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
});
