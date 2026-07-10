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
import Settings from "./settings";
import type { ApiKeyOut, WorkspaceSettings } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getSessionToken: vi.fn(),
    clearSessionToken: vi.fn(),
    getWorkspaceSettings: vi.fn(),
    updateWorkspaceSettings: vi.fn(),
    listApiKeys: vi.fn(),
    addApiKey: vi.fn(),
    deleteApiKey: vi.fn(),
  };
});

import {
  addApiKey,
  deleteApiKey,
  getSessionToken,
  getWorkspaceSettings,
  listApiKeys,
  updateWorkspaceSettings,
} from "@/lib/api";

// TanStack Router's scroll restoration calls window.scrollTo, which jsdom
// doesn't implement - stub it out (same pattern as the other route tests).
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

function baseWorkspace(overrides: Partial<WorkspaceSettings> = {}): WorkspaceSettings {
  return { name: "Acme workspace", ...overrides };
}

function baseKey(overrides: Partial<ApiKeyOut> = {}): ApiKeyOut {
  return {
    id: 1,
    provider: "openai",
    last_four: "a1b2",
    created_at: "2026-01-15T12:00:00Z",
    ...overrides,
  };
}

function renderSettings() {
  const rootRoute = createRootRoute();
  const settingsRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/settings",
    component: Settings,
  });
  const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: () => null });
  const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: () => null });
  const routeTree = rootRoute.addChildren([settingsRoute, homeRoute, loginRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/settings"] }),
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
  vi.mocked(getSessionToken).mockReset();
  vi.mocked(getWorkspaceSettings).mockReset();
  vi.mocked(updateWorkspaceSettings).mockReset();
  vi.mocked(listApiKeys).mockReset();
  vi.mocked(addApiKey).mockReset();
  vi.mocked(deleteApiKey).mockReset();
});

describe("Settings", () => {
  it("prompts sign-in when there is no session token", async () => {
    vi.mocked(getSessionToken).mockReturnValue(null);

    renderSettings();

    expect(
      await screen.findByText("Sign in to manage your workspace settings.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to sign in" })).toBeInTheDocument();
    expect(getWorkspaceSettings).not.toHaveBeenCalled();
  });

  it("shows the workspace name and the configured API keys once signed in", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([baseKey()]);

    renderSettings();

    expect(await screen.findByDisplayValue("Acme workspace")).toBeInTheDocument();
    expect(await screen.findByText("openai")).toBeInTheDocument();
    expect(screen.getByText("sk-…a1b2")).toBeInTheDocument();
    // The full key is never shown, only the last four.
    expect(screen.queryByText(/sk-[a-zA-Z0-9]{5,}/)).not.toBeInTheDocument();
  });

  it("saves a renamed workspace", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(updateWorkspaceSettings).mockResolvedValue({ name: "Renamed workspace" });

    renderSettings();

    const nameInput = await screen.findByLabelText("Workspace name");
    fireEvent.change(nameInput, { target: { value: "Renamed workspace" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateWorkspaceSettings).toHaveBeenCalledWith("Renamed workspace");
    });
  });

  it("the save button is disabled until the name actually changes", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);

    renderSettings();

    await screen.findByDisplayValue("Acme workspace");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("adds an API key and clears the form so the key never reappears", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys)
      .mockResolvedValueOnce([]) // initial load
      .mockResolvedValueOnce([baseKey({ provider: "anthropic", last_four: "z9y8" })]); // after add
    vi.mocked(addApiKey).mockResolvedValue(
      baseKey({ provider: "anthropic", last_four: "z9y8" })
    );

    renderSettings();

    await screen.findByText("No API keys configured yet.");

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "anthropic" } });
    const keyInput = screen.getByLabelText("API key");
    fireEvent.change(keyInput, { target: { value: "sk-ant-abcdz9y8" } });
    fireEvent.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() => {
      expect(addApiKey).toHaveBeenCalledWith("anthropic", "sk-ant-abcdz9y8");
    });

    // Form clears the raw key input after a successful save.
    await waitFor(() => {
      expect((keyInput as HTMLInputElement).value).toBe("");
    });

    // The newly added key shows up with only its last four visible.
    expect(await screen.findByText("anthropic")).toBeInTheDocument();
    expect(screen.getByText("sk-…z9y8")).toBeInTheDocument();
  });

  it("shows a free-text provider input when 'Other' is selected", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);
    vi.mocked(addApiKey).mockResolvedValue(baseKey({ provider: "together", last_four: "wxyz" }));

    renderSettings();

    await screen.findByText("No API keys configured yet.");

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "other" } });
    const customProviderInput = await screen.findByLabelText("Provider name");
    fireEvent.change(customProviderInput, { target: { value: "together" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-togetherwxyz" } });
    fireEvent.click(screen.getByRole("button", { name: "Add API key" }));

    await waitFor(() => {
      expect(addApiKey).toHaveBeenCalledWith("together", "sk-togetherwxyz");
    });
  });

  it("deletes an API key", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys)
      .mockResolvedValueOnce([baseKey()])
      .mockResolvedValueOnce([]);
    vi.mocked(deleteApiKey).mockResolvedValue(undefined);

    renderSettings();

    await screen.findByText("openai");
    fireEvent.click(screen.getByRole("button", { name: "Delete openai key" }));

    await waitFor(() => {
      expect(deleteApiKey).toHaveBeenCalledWith(1);
    });

    await waitFor(() => {
      expect(screen.getByText("No API keys configured yet.")).toBeInTheDocument();
    });
  });

  it("the add button is disabled until a provider and key are entered", async () => {
    vi.mocked(getSessionToken).mockReturnValue("session-token");
    vi.mocked(getWorkspaceSettings).mockResolvedValue(baseWorkspace());
    vi.mocked(listApiKeys).mockResolvedValue([]);

    renderSettings();

    await screen.findByText("No API keys configured yet.");
    expect(screen.getByRole("button", { name: "Add API key" })).toBeDisabled();
  });
});
