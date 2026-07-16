import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DataTable } from "./data-table";
import type { DagResponse, StageRecordsPage } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getPipelineDag: vi.fn(),
    listStageRecords: vi.fn(),
  };
});

import { getPipelineDag, listStageRecords } from "@/lib/api";

beforeAll(() => {
  // @tanstack/react-virtual's useVirtualizer measures the scroll container's
  // size to decide which rows are "visible" - jsdom elements default to a 0
  // offsetHeight/offsetWidth (no real layout engine), which would make the
  // virtualizer think the viewport is zero-sized and render no rows at all.
  // Stubbing a real-ish size, same spirit as pipeline-workspace.test.tsx's
  // note on @xyflow/react needing browser APIs jsdom doesn't provide.
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    value: 600,
  });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    value: 900,
  });
  // @ts-expect-error - jsdom doesn't implement ResizeObserver
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

function baseDag(): DagResponse {
  return {
    pipeline_id: 1,
    layers: [{ stage_ids: [10, 20] }],
    stages: {
      "10": {
        id: 10,
        name: "Extract",
        model: "gpt-4o",
        avg_tokens_in: 1,
        avg_tokens_out: 1,
        avg_latency_ms: 1,
      },
      "20": {
        id: 20,
        name: "Summarize",
        model: "gpt-4o",
        avg_tokens_in: 1,
        avg_tokens_out: 1,
        avg_latency_ms: 1,
      },
    },
    edges: [],
  };
}

function page(records: StageRecordsPage["records"]): StageRecordsPage {
  return { records, next_cursor: null };
}

function renderTable() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DataTable pipelineId={1} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(getPipelineDag).mockReset();
  vi.mocked(listStageRecords).mockReset();
  vi.mocked(getPipelineDag).mockResolvedValue(baseDag());
});

describe("DataTable", () => {
  it("populates the stage filter from the pipeline's DAG, defaulting to All stages", async () => {
    vi.mocked(listStageRecords).mockResolvedValue(page([]));

    renderTable();

    const select = await screen.findByLabelText("Stage");
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Extract" })).toBeInTheDocument();
    });
    expect(screen.getByRole("option", { name: "Summarize" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All stages" })).toBeInTheDocument();
    expect(select).toHaveValue("");
  });

  it("shows an empty state when the pipeline has no stage records", async () => {
    vi.mocked(listStageRecords).mockResolvedValue(page([]));

    renderTable();

    expect(await screen.findByText("No stage records for this pipeline yet.")).toBeInTheDocument();
  });

  it("truncates long row content and shows the full untruncated content in the drawer on click", async () => {
    const longPrompt = "P".repeat(200);
    const longOutput = "O".repeat(200);
    vi.mocked(listStageRecords).mockResolvedValue(
      page([
        {
          id: 1,
          stage_id: 10,
          stage_name: "Extract",
          trace_id: 5,
          input: { q: "hello" },
          rendered_prompt: longPrompt,
          output: longOutput,
          tokens_in: 12,
          tokens_out: 34,
          latency_ms: 456,
          cost: 0.0123,
        },
      ])
    );

    renderTable();

    await screen.findByText('{"q":"hello"}');
    // Full strings must not appear as a single row-cell text node (truncated).
    expect(screen.queryByText(longPrompt)).not.toBeInTheDocument();
    expect(screen.queryByText(longOutput)).not.toBeInTheDocument();

    const rowButtons = screen.getAllByRole("button").filter((b) => b.textContent?.includes("Extract"));
    fireEvent.click(rowButtons[0]);

    // Drawer shows the full, untruncated content.
    expect(await screen.findByText(longPrompt)).toBeInTheDocument();
    expect(screen.getByText(longOutput)).toBeInTheDocument();
    expect(screen.getByText("Tokens in: 12")).toBeInTheDocument();
    expect(screen.getByText("Tokens out: 34")).toBeInTheDocument();
    expect(screen.getByText("Cost: $0.0123")).toBeInTheDocument();
    expect(screen.getByText("Latency: 456ms")).toBeInTheDocument();
  });

  it("re-fetches scoped to the selected stage when the stage filter changes", async () => {
    vi.mocked(listStageRecords).mockResolvedValue(page([]));

    renderTable();

    await waitFor(() => {
      expect(listStageRecords).toHaveBeenCalledWith(1, { stageId: null, cursor: 0, limit: 50 });
    });

    const select = await screen.findByLabelText("Stage");
    fireEvent.change(select, { target: { value: "20" } });

    await waitFor(() => {
      expect(listStageRecords).toHaveBeenCalledWith(1, { stageId: 20, cursor: 0, limit: 50 });
    });
  });
});
