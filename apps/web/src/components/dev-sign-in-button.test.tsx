import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DevSignInButton } from "./dev-sign-in-button";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    requestMagicLink: vi.fn(),
    verifyMagicLink: vi.fn(),
    setSessionToken: vi.fn(),
  };
});

import { requestMagicLink, setSessionToken, verifyMagicLink } from "@/lib/api";

function renderButton(props: { email?: string; onSignedIn: () => void }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DevSignInButton {...props} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(requestMagicLink).mockReset();
  vi.mocked(verifyMagicLink).mockReset();
  vi.mocked(setSessionToken).mockReset();
});

describe("DevSignInButton", () => {
  it("requests a magic link, follows it, stores the session and reports success", async () => {
    vi.mocked(requestMagicLink).mockResolvedValue({
      message: "sent",
      dev_magic_link: "http://localhost:5173/auth/verify?token=tok-123",
    });
    vi.mocked(verifyMagicLink).mockResolvedValue({
      session_token: "session-abc",
      user: { id: 1, email: "dev@example.com" },
      workspace: { id: 1, name: "Dev workspace" },
    });
    const onSignedIn = vi.fn();

    renderButton({ email: "someone@example.com", onSignedIn });
    fireEvent.click(screen.getByRole("button", { name: "Sign in (dev)" }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    expect(requestMagicLink).toHaveBeenCalledWith("someone@example.com");
    expect(verifyMagicLink).toHaveBeenCalledWith("tok-123");
    expect(setSessionToken).toHaveBeenCalledWith("session-abc");
  });

  it("falls back to a fixed dev address when no email is given", async () => {
    vi.mocked(requestMagicLink).mockResolvedValue({
      message: "sent",
      dev_magic_link: "http://localhost:5173/auth/verify?token=tok-9",
    });
    vi.mocked(verifyMagicLink).mockResolvedValue({
      session_token: "s",
      user: { id: 1, email: "dev@example.com" },
      workspace: { id: 1, name: "Dev workspace" },
    });

    renderButton({ onSignedIn: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: "Sign in (dev)" }));

    await waitFor(() => expect(requestMagicLink).toHaveBeenCalledWith("dev@example.com"));
  });

  it("explains itself instead of failing silently when the API is not in dev mode", async () => {
    vi.mocked(requestMagicLink).mockResolvedValue({
      message: "sent",
      dev_magic_link: null,
    });
    const onSignedIn = vi.fn();

    renderButton({ onSignedIn });
    fireEvent.click(screen.getByRole("button", { name: "Sign in (dev)" }));

    expect(
      await screen.findByText(
        "The API isn't in dev magic-link mode — use the email sign-in flow instead."
      )
    ).toBeInTheDocument();
    expect(verifyMagicLink).not.toHaveBeenCalled();
    expect(setSessionToken).not.toHaveBeenCalled();
    expect(onSignedIn).not.toHaveBeenCalled();
  });
});
