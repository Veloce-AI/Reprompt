import { createRouter, createRoute, createRootRoute } from "@tanstack/react-router";
import Home from "./routes/home";
import DevKit from "./routes/dev-kit";

const rootRoute = createRootRoute({
  component: () => <Home />,
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

const routeTree = rootRoute.addChildren([homeRoute, devKitRoute]);

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export default router;
