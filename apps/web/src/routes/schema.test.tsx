import { describe, it, expect, vi, beforeEach } from "vitest";
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
import SchemaReference from "./schema";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getTraceFormatSchema: vi.fn(),
  };
});

import { getTraceFormatSchema } from "@/lib/api";

// TanStack Router's scroll restoration calls window.scrollTo, which jsdom
// doesn't implement - stub it out (same pattern as the other route tests).
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

function renderSchemaPage() {
  const rootRoute = createRootRoute();
  const schemaRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/schema",
    component: SchemaReference,
  });
  const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: () => null });
  const routeTree = rootRoute.addChildren([schemaRoute, homeRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/schema"] }),
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
  vi.mocked(getTraceFormatSchema).mockReset();
  // jsdom doesn't implement the Blob URL APIs the download flow uses.
  URL.createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  // jsdom logs a "Not implemented: navigation" error when a real click on an
  // <a href="blob:..."> element fires - the download flow doesn't need an
  // actual navigation to happen for the test, just the click to occur.
  HTMLAnchorElement.prototype.click = vi.fn();
});

describe("SchemaReference", () => {
  it("renders the plain-English intro", async () => {
    renderSchemaPage();

    expect(
      await screen.findByText(/Refract ingests execution traces from any AI pipeline/)
    ).toBeInTheDocument();
  });

  it("renders the object-graph diagram section", async () => {
    renderSchemaPage();

    expect(await screen.findByText("The shape, in short")).toBeInTheDocument();
    expect(screen.getByText(/StageRecord\[\]/)).toBeInTheDocument();
  });

  it("renders a required vs optional fields table covering the core fields", async () => {
    renderSchemaPage();

    await screen.findByText("Required vs optional fields");

    // Required core fields called out in the intro.
    expect(screen.getAllByText("prompt_template").length).toBeGreaterThan(0);
    expect(screen.getAllByText("query").length).toBeGreaterThan(0);
    expect(screen.getAllByText("output").length).toBeGreaterThan(0);

    // Optional fields, including the v1.1 additions.
    expect(screen.getAllByText("tokens").length).toBeGreaterThan(0);
    expect(screen.getAllByText("latency_ms").length).toBeGreaterThan(0);
    expect(screen.getAllByText("documents").length).toBeGreaterThan(0);
    expect(screen.getAllByText("metadata").length).toBeGreaterThan(0);
    expect(screen.getAllByText("system_prompt").length).toBeGreaterThan(0);

    expect(screen.getAllByText("Required").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Optional").length).toBeGreaterThan(0);
  });

  it("renders a minimal JSON example showing traces with and without tokens", async () => {
    renderSchemaPage();

    await screen.findByText("Minimal example");
    // The two trace ids show token accounting is optional per-trace.
    expect(screen.getByText(/"trace-001"/)).toBeInTheDocument();
    expect(screen.getByText(/"trace-002"/)).toBeInTheDocument();
  });

  it("points at the trace recorder example file for a copy-paste starting point", async () => {
    renderSchemaPage();

    expect(await screen.findByText("docs/examples/trace_recorder.py")).toBeInTheDocument();
  });

  it("fetches and downloads the raw JSON schema when the button is clicked", async () => {
    vi.mocked(getTraceFormatSchema).mockResolvedValue({ type: "object", title: "TraceFile" });

    renderSchemaPage();

    fireEvent.click(await screen.findByRole("button", { name: "Download JSON schema" }));

    await waitFor(() => {
      expect(getTraceFormatSchema).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(URL.createObjectURL).toHaveBeenCalled();
    });
  });

  it("shows an error message if the schema fetch fails", async () => {
    vi.mocked(getTraceFormatSchema).mockRejectedValue(new Error("network error"));

    renderSchemaPage();

    fireEvent.click(await screen.findByRole("button", { name: "Download JSON schema" }));

    expect(
      await screen.findByText("Couldn't fetch the schema. Check your connection and try again.")
    ).toBeInTheDocument();
  });
});
