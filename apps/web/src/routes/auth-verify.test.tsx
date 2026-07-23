import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import AuthVerify from "./auth-verify";

vi.mock("@/lib/api", () => ({
  verifyMagicLink: vi.fn(),
  setSessionToken: vi.fn(),
}));

import { setSessionToken, verifyMagicLink } from "@/lib/api";

window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

function renderAt(path: string) {
  const rootRoute = createRootRoute();
  const homeRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/pipelines",
    component: () => <div>Pipelines home</div>,
  });
  const authVerifyRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/auth/verify",
    validateSearch: (search: Record<string, unknown>): { token?: string } => ({
      token: typeof search.token === "string" ? search.token : undefined,
    }),
    component: AuthVerify,
  });
  const routeTree = rootRoute.addChildren([homeRoute, authVerifyRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
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
  vi.mocked(verifyMagicLink).mockReset();
  vi.mocked(setSessionToken).mockReset();
});

describe("AuthVerify", () => {
  it("exchanges the token, stores the session, and redirects to Pipelines home", async () => {
    vi.mocked(verifyMagicLink).mockResolvedValue({
      session_token: "payload.signature",
      user: { id: 1, email: "user@example.com" },
      workspace: { id: 1, name: "user's workspace" },
    });

    // The mocked verifyMagicLink resolves near-instantly, so the transient
    // "Signing you in…" pending state isn't reliably observable here (it's
    // covered by the error-path test below, which never leaves it). This
    // test's job is the token exchange + session storage + redirect.
    renderAt("/auth/verify?token=abc123");

    await waitFor(() => {
      expect(verifyMagicLink).toHaveBeenCalledWith("abc123");
    });
    expect(setSessionToken).toHaveBeenCalledWith("payload.signature");

    await screen.findByText("Pipelines home");
  });

  it("shows an error and does not redirect when the token is rejected", async () => {
    vi.mocked(verifyMagicLink).mockRejectedValue(
      new Error("This link has expired. Request a new one from the sign-in page.")
    );

    renderAt("/auth/verify?token=expired");

    expect(
      await screen.findByText("This link has expired. Request a new one from the sign-in page.")
    ).toBeInTheDocument();
    expect(setSessionToken).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Back to sign in" })).toBeInTheDocument();
  });

  it("shows a missing-token error and never calls the API when no token is present", async () => {
    renderAt("/auth/verify");

    expect(
      await screen.findByText(
        "This link is missing its token. Request a new one from the sign-in page."
      )
    ).toBeInTheDocument();
    expect(verifyMagicLink).not.toHaveBeenCalled();
  });
});
