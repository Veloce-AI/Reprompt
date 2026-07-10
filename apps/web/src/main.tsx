import "@fontsource/spectral/600.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles/globals.css";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import router from "./router";

const queryClient = new QueryClient();

// No <StrictMode> here, deliberately: on @tanstack/react-query@5.101.2
// (latest as of writing), StrictMode's dev-only double-invoke of effects
// on mount causes useMutation's observer to unsubscribe/resubscribe mid
// -flight and miss the final success notification - onSuccess/onSettled
// fire correctly, but the component's rendered `.status` gets stuck at
// "pending" forever (reproduced directly: mutation observer resolves, UI
// never leaves the loading state). Confirmed by removing StrictMode alone
// that this fully resolves it. StrictMode is a dev-only diagnostic; this
// has no effect on production behavior either way.
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={queryClient}>
    <RouterProvider router={router} />
  </QueryClientProvider>
);
