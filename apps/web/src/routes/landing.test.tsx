import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import Landing from "./landing";
import { setSessionToken, clearSessionToken } from "@/lib/api";

window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

// jsdom implements neither API - the reduced-motion cycle hooks and the
// scroll-reveal wrapper both need a stub to render at all in tests.
window.matchMedia =
  window.matchMedia ??
  ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;

class MockIntersectionObserver implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds: ReadonlyArray<number> = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => []);
}
window.IntersectionObserver = MockIntersectionObserver as unknown as typeof IntersectionObserver;

function renderLanding() {
  const rootRoute = createRootRoute();
  const landingRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Landing });
  const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: () => null });
  const pipelinesRoute = createRoute({ getParentRoute: () => rootRoute, path: "/pipelines", component: () => null });
  const schemaRoute = createRoute({ getParentRoute: () => rootRoute, path: "/schema", component: () => null });
  const routeTree = rootRoute.addChildren([landingRoute, loginRoute, pipelinesRoute, schemaRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return render(<RouterProvider router={router} />);
}

afterEach(() => {
  clearSessionToken();
});

describe("Landing", () => {
  it("renders the hero headline and a sign-in CTA", async () => {
    renderLanding();

    expect(
      await screen.findByText("Change the AI model behind your product without breaking it — and prove it.")
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Sign in/ }).length).toBeGreaterThan(0);
  });

  it("shows the trace stage sequence", async () => {
    renderLanding();

    expect(await screen.findByText("Classify")).toBeInTheDocument();
    // "Search" also appears as one of the five "how it works" step titles
    // further down the page - assert at least the trace chip's copy exists.
    expect(screen.getAllByText("Search").length).toBeGreaterThan(0);
    expect(screen.getByText("Summarize")).toBeInTheDocument();
    expect(screen.getByText("Answer")).toBeInTheDocument();
  });

  it("shows the Prism step sequence and round cap", async () => {
    renderLanding();

    expect(await screen.findByText("Mutate")).toBeInTheDocument();
    expect(screen.getByText("Critique")).toBeInTheDocument();
    expect(screen.getByText(/up to 3 refine rounds/)).toBeInTheDocument();
  });

  it("shows an example scorecard via ParityBeam", async () => {
    renderLanding();

    expect(await screen.findByRole("meter", { name: /Parity score 97%/ })).toBeInTheDocument();
  });

  it("links the footer to the trace format reference", async () => {
    renderLanding();

    expect(await screen.findByRole("link", { name: "Trace format reference" })).toHaveAttribute(
      "href",
      "/schema"
    );
  });

  it("shows the landing page (not a redirect) to a signed-in visitor, with CTAs pointed at Pipelines", async () => {
    setSessionToken("a-real-session-token");
    renderLanding();

    expect(
      await screen.findByText("Change the AI model behind your product without breaking it — and prove it.")
    ).toBeInTheDocument();
    const ctas = screen.getAllByRole("link", { name: /Go to Pipelines/ });
    expect(ctas.length).toBeGreaterThan(0);
    for (const cta of ctas) {
      expect(cta).toHaveAttribute("href", "/pipelines");
    }
    expect(screen.queryByRole("link", { name: /^Sign in/ })).not.toBeInTheDocument();
  });
});
