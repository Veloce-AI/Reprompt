import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
import Home from "./home";
import type { PipelineSummary } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listPipelines: vi.fn(),
    deletePipeline: vi.fn(),
  };
});

import { listPipelines, deletePipeline } from "@/lib/api";

// TanStack Router's scroll restoration calls window.scrollTo, which jsdom
// doesn't implement - stub it out (same pattern as the other route tests).
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

function basePipeline(overrides: Partial<PipelineSummary> = {}): PipelineSummary {
  return {
    id: 1,
    name: "Financial Extraction Pipeline",
    stage_count: 4,
    models_used: ["gpt-4o"],
    benchmark_query_count: 12,
    ...overrides,
  };
}

function renderHome() {
  const rootRoute = createRootRoute();
  const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Home });
  const importRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines/import",
    component: () => null,
  });
  const pipelineRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines/$pipelineId",
    component: () => null,
  });
  const schemaRoute = createRoute({ getParentRoute: () => rootRoute, path: "/schema", component: () => null });
  const routeTree = rootRoute.addChildren([homeRoute, importRoute, pipelineRoute, schemaRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return { router, ...render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  ) };
}

beforeEach(() => {
  vi.mocked(listPipelines).mockReset();
  vi.mocked(deletePipeline).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Home (pipelines list)", () => {
  it("shows a delete button per pipeline row", async () => {
    vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);

    renderHome();

    expect(
      await screen.findByRole("button", { name: "Delete Financial Extraction Pipeline" })
    ).toBeInTheDocument();
  });

  it("asks for confirmation and does not delete when the user cancels", async () => {
    vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderHome();

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Financial Extraction Pipeline" })
    );

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining("Financial Extraction Pipeline")
    );
    expect(deletePipeline).not.toHaveBeenCalled();
  });

  it("deletes the pipeline and removes it from the list once confirmed", async () => {
    vi.mocked(listPipelines)
      .mockResolvedValueOnce([basePipeline()]) // initial load
      .mockResolvedValueOnce([]); // after delete, refetched
    vi.mocked(deletePipeline).mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderHome();

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Financial Extraction Pipeline" })
    );

    await waitFor(() => {
      expect(deletePipeline).toHaveBeenCalledWith(1);
    });

    await waitFor(() => {
      expect(
        screen.queryByText("Financial Extraction Pipeline")
      ).not.toBeInTheDocument();
    });
  });

  it("clicking the delete button does not navigate into the pipeline row", async () => {
    vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    const { router } = renderHome();

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Financial Extraction Pipeline" })
    );

    expect(router.state.location.pathname).toBe("/");
  });

  it("surfaces an error if the delete request fails", async () => {
    vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);
    vi.mocked(deletePipeline).mockRejectedValue(new Error("Pipeline not found"));
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderHome();

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Financial Extraction Pipeline" })
    );

    expect(await screen.findByText(/Couldn't delete pipeline/)).toBeInTheDocument();
  });

  it("shows an edit button per pipeline row", async () => {
    vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);

    renderHome();

    expect(
      await screen.findByRole("button", { name: "Edit Financial Extraction Pipeline" })
    ).toBeInTheDocument();
  });

  it("edit button triggers inline rename input, same as clicking the name", async () => {
    vi.mocked(listPipelines).mockResolvedValue([basePipeline()]);

    renderHome();

    const editButton = await screen.findByRole("button", { name: "Edit Financial Extraction Pipeline" });
    fireEvent.click(editButton);

    const renameInput = await screen.findByRole("textbox", { name: "Pipeline name" });
    expect(renameInput).toBeInTheDocument();
    expect((renameInput as HTMLInputElement).value).toBe("Financial Extraction Pipeline");
  });
});
