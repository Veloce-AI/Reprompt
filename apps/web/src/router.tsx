import { createRouter, createRoute, createRootRoute, Outlet } from "@tanstack/react-router";
import Home from "./routes/home";
import DevKit from "./routes/dev-kit";
import PipelinesImport from "./routes/pipelines-import";
import PipelineDetail from "./routes/pipeline-detail";
import RubricReview from "./routes/rubric-review";

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

const routeTree = rootRoute.addChildren([
  homeRoute,
  devKitRoute,
  pipelinesImportRoute,
  pipelineDetailRoute,
  rubricReviewRoute,
]);

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export default router;
