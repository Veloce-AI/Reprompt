import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import RubricReview from "./rubric-review";
import type { RubricOut } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  listRubrics: vi.fn(),
  updateRubric: vi.fn(),
  approveRubric: vi.fn(),
  approveAllRubrics: vi.fn(),
}));

import { approveAllRubrics, approveRubric, listRubrics, updateRubric } from "@/lib/api";

// TanStack Router's scroll restoration calls window.scrollTo, which jsdom
// doesn't implement - stub it out so it doesn't spam stderr on every route
// mount. Purely cosmetic; tests already pass without this.
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

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

function renderAtPipeline(pipelineId: string) {
  const rootRoute = createRootRoute();
  const rubricRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines/$pipelineId/rubrics",
    component: RubricReview,
  });
  const routeTree = rootRoute.addChildren([rubricRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [`/pipelines/${pipelineId}/rubrics`] }),
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
  vi.mocked(listRubrics).mockReset();
  vi.mocked(updateRubric).mockReset();
  vi.mocked(approveRubric).mockReset();
  vi.mocked(approveAllRubrics).mockReset();
});

describe("RubricReview", () => {
  it("renders plain-English sentences for each check, never the raw check type", async () => {
    vi.mocked(listRubrics).mockResolvedValue([baseRubric()]);

    renderAtPipeline("1");

    await screen.findByText("Extract financials");
    expect(screen.getByText("Must include: currency, revenue")).toBeInTheDocument();
    expect(
      screen.getByText("Length must be between 20 and 800 characters")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Covers all key entities/)
    ).toBeInTheDocument();
    expect(screen.getByText("Next stage reads: currency")).toBeInTheDocument();

    // Never shows the raw check type or jargon like "json schema" as body text.
    expect(screen.queryByText("required_keys")).not.toBeInTheDocument();
    expect(screen.queryByText(/json schema/i)).not.toBeInTheDocument();
  });

  it("groups items into Format checks / Content criteria / Downstream contract", async () => {
    vi.mocked(listRubrics).mockResolvedValue([baseRubric()]);

    renderAtPipeline("1");

    await screen.findByText("Extract financials");
    expect(screen.getByText("Format checks")).toBeInTheDocument();
    expect(screen.getByText("Content criteria")).toBeInTheDocument();
    expect(screen.getByText("Downstream contract")).toBeInTheDocument();
  });

  it("deletes a format check and PATCHes the remaining list", async () => {
    const rubric = baseRubric();
    vi.mocked(listRubrics).mockResolvedValue([rubric]);
    vi.mocked(updateRubric).mockImplementation(async (_id, patch) => ({ ...rubric, ...patch }));

    renderAtPipeline("1");
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

  it("adds a new content criterion via the Add criterion input", async () => {
    const rubric = baseRubric();
    vi.mocked(listRubrics).mockResolvedValue([rubric]);
    vi.mocked(updateRubric).mockImplementation(async (_id, patch) => ({ ...rubric, ...patch }));

    renderAtPipeline("1");
    await screen.findByText("Content criteria");

    const input = screen.getByLabelText("Add a content criterion name");
    fireEvent.change(input, { target: { value: "No hedging language" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Add criterion" })[1]);

    await waitFor(() => {
      expect(updateRubric).toHaveBeenCalledWith(1, {
        judge_criteria: [
          ...rubric.judge_criteria,
          { name: "No hedging language", weight: 1, description: "" },
        ],
      });
    });
  });

  it("approves a single stage and reflects the approved badge", async () => {
    const rubric = baseRubric();
    vi.mocked(listRubrics).mockResolvedValue([rubric]);
    vi.mocked(approveRubric).mockResolvedValue({ ...rubric, approved: true });

    renderAtPipeline("1");
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

    renderAtPipeline("1");
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

    renderAtPipeline("1");

    expect(await screen.findByText("No rubrics yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve all" })).not.toBeInTheDocument();
  });
});
