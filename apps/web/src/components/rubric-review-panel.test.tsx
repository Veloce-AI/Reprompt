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
}));

import {
  approveAllRubrics,
  approveRubric,
  getPipelineDag,
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
  vi.mocked(listRubrics).mockReset();
  vi.mocked(updateRubric).mockReset();
  vi.mocked(approveRubric).mockReset();
  vi.mocked(approveAllRubrics).mockReset();
  vi.mocked(getPipelineDag).mockReset();
  vi.mocked(getPipelineDag).mockResolvedValue({
    pipeline_id: 1,
    layers: [],
    stages: {},
    edges: [],
  });
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
});
