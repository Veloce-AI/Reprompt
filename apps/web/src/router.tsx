import { createRouter, createRoute, createRootRoute, Outlet } from "@tanstack/react-router";
import Home from "./routes/home";
import DevKit from "./routes/dev-kit";
import PipelinesImport from "./routes/pipelines-import";
import PipelineDetail from "./routes/pipeline-detail";
import RubricReview from "./routes/rubric-review";
import NewMigration from "./routes/new-migration";
import MigrationDetail from "./routes/migration-detail";
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

const migrationDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pipelines/$pipelineId/migrations/$migrationId",
  component: MigrationDetail,
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
  pipelineDetailRoute,
  rubricReviewRoute,
  newMigrationRoute,
  migrationDetailRoute,
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
