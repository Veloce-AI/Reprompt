import { createRouter, createRoute, createRootRoute, Outlet } from "@tanstack/react-router";
import Home from "./routes/home";
import DevKit from "./routes/dev-kit";
import PipelinesImport from "./routes/pipelines-import";
import PipelineDetail from "./routes/pipeline-detail";
import RubricReview from "./routes/rubric-review";
import NewMigration from "./routes/new-migration";
import Login from "./routes/login";
import AuthVerify from "./routes/auth-verify";
import Settings from "./routes/settings";

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

const pipelineDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/$pipelineId",
  component: PipelineDetail,
});

const rubricReviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/$pipelineId/rubrics",
  component: RubricReview,
});

const newMigrationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/$pipelineId/migrations/new",
  component: NewMigration,
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

const routeTree = rootRoute.addChildren([
  homeRoute,
  devKitRoute,
  pipelinesImportRoute,
  pipelineDetailRoute,
  rubricReviewRoute,
  newMigrationRoute,
  loginRoute,
  authVerifyRoute,
  settingsRoute,
]);

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export default router;
