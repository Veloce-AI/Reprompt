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
import Login from "./login";

vi.mock("@/lib/api", () => ({
  requestMagicLink: vi.fn(),
}));

import { requestMagicLink } from "@/lib/api";

window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

function renderLogin() {
  const rootRoute = createRootRoute();
  const loginRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/login",
    component: Login,
  });
  const routeTree = rootRoute.addChildren([loginRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/login"] }),
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
  vi.mocked(requestMagicLink).mockReset();
});

describe("Login", () => {
  it("renders an email input and a sentence-case submit button", async () => {
    renderLogin();

    expect(await screen.findByLabelText("Email address")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send magic link" })).toBeInTheDocument();
  });

  it("submits the trimmed email and shows the confirmation state", async () => {
    vi.mocked(requestMagicLink).mockResolvedValue({
      message: "If that address can receive mail, a sign-in link is on its way.",
      dev_magic_link: null,
    });

    renderLogin();

    fireEvent.change(await screen.findByLabelText("Email address"), {
      target: { value: "  user@example.com  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send magic link" }));

    await waitFor(() => {
      expect(requestMagicLink).toHaveBeenCalledWith("user@example.com");
    });

    expect(await screen.findByText("Check your email for a link")).toBeInTheDocument();
    // No dev link was returned - nothing dev-only should be shown.
    expect(screen.queryByText(/Dev-only fallback/)).not.toBeInTheDocument();
  });

  it("shows the dev-mode magic link as a clickable link when the API returns one", async () => {
    vi.mocked(requestMagicLink).mockResolvedValue({
      message: "If that address can receive mail, a sign-in link is on its way.",
      dev_magic_link: "http://localhost:5173/auth/verify?token=abc123",
    });

    renderLogin();

    fireEvent.change(await screen.findByLabelText("Email address"), {
      target: { value: "dev@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send magic link" }));

    await screen.findByText("Check your email for a link");
    expect(screen.getByText(/Dev-only fallback/)).toBeInTheDocument();
    const link = screen.getByRole("link", {
      name: "http://localhost:5173/auth/verify?token=abc123",
    });
    expect(link).toHaveAttribute("href", "http://localhost:5173/auth/verify?token=abc123");
  });

  it("shows an error message and stays on the form when the request fails", async () => {
    vi.mocked(requestMagicLink).mockRejectedValue(new Error("Enter a valid email address."));

    renderLogin();

    fireEvent.change(await screen.findByLabelText("Email address"), {
      target: { value: "user@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send magic link" }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    // Still on the form, not the confirmation state.
    expect(screen.getByRole("button", { name: "Send magic link" })).toBeInTheDocument();
  });

  it("does not submit on an empty email", async () => {
    renderLogin();

    fireEvent.click(await screen.findByRole("button", { name: "Send magic link" }));

    expect(requestMagicLink).not.toHaveBeenCalled();
  });
});
