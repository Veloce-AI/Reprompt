import { createRouter, createRoute, createRootRoute, Outlet, redirect } from "@tanstack/react-router";
import Home from "./routes/home";
import DevKit from "./routes/dev-kit";
import PipelinesImport from "./routes/pipelines-import";
import PipelineWorkspace, { WORKSPACE_TABS, type WorkspaceTab } from "./routes/pipeline-workspace";
import Login from "./routes/login";
import AuthVerify from "./routes/auth-verify";
import Settings from "./routes/settings";
import SchemaReference from "./routes/schema";

const rootRoute = createRootRoute({
  component: () => <Outlet />,
});

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Home,
});

const devKitRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dev/kit",
  component: DevKit,
});

const pipelinesImportRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/import",
  component: PipelinesImport,
});

// Tab state lives in the URL, not local component state, so switching tabs
// is a normal navigation (back/forward, bookmarking, and the redirect stubs
// below all just work). Falls back to "canvas" for a missing/unrecognized
// value rather than erroring - a stale bookmark or a manually-edited URL
// should still land somewhere sensible.
function validateWorkspaceSearch(search: Record<string, unknown>): { tab: WorkspaceTab } {
  const raw = typeof search.tab === "string" ? search.tab : undefined;
  const tab = (WORKSPACE_TABS as readonly string[]).includes(raw ?? "")
    ? (raw as WorkspaceTab)
    : "canvas";
  return { tab };
}

const pipelineWorkspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/$pipelineId",
  validateSearch: validateWorkspaceSearch,
  component: PipelineWorkspace,
});

// Old standalone screens, now tabs of the unified workspace (see
// DEV_TRACKER.md's "Phase 1 — Unified pipeline workspace"). These paths
// have no component of their own anymore - any bookmarked/shared link to
// them just redirects into the matching tab, so nothing breaks.
const rubricReviewRedirectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/$pipelineId/rubrics",
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/pipelines/$pipelineId",
      params,
      search: { tab: "rubrics" },
    });
  },
});

const newMigrationRedirectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/$pipelineId/migrations/new",
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/pipelines/$pipelineId",
      params,
      search: { tab: "migrations" },
    });
  },
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: Login,
});

// search-param validation, not a path param: the token travels in the
// magic-link URL's query string (`/auth/verify?token=...`), same shape the
// API itself hands back in `dev_magic_link` (see auth.py / api.ts).
const authVerifyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/auth/verify",
  validateSearch: (search: Record<string, unknown>): { token?: string } => ({
    token: typeof search.token === "string" ? search.token : undefined,
  }),
  component: AuthVerify,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: Settings,
});

const schemaRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/schema",
  component: SchemaReference,
});

const routeTree = rootRoute.addChildren([
  homeRoute,
  devKitRoute,
  pipelinesImportRoute,
  pipelineWorkspaceRoute,
  rubricReviewRedirectRoute,
  newMigrationRedirectRoute,
  loginRoute,
  authVerifyRoute,
  settingsRoute,
  schemaRoute,
]);

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export default router;
