import type { ErrorComponentProps } from "@tanstack/react-router";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

/**
 * App-wide render-error fallback, wired as the root route's `errorComponent`
 * (see router.tsx). Without this, TanStack Router's own default error UI is
 * a bare, unstyled "Something went wrong!" line with no nav, no branding,
 * nothing else on the page — which is visually indistinguishable from a
 * genuinely blank/broken page at a glance (this is exactly the shape of a
 * real "the page is empty" report investigated in DEV_TRACKER.md's
 * "Settings page reported empty" section: none of the three real states
 * — unauthenticated, zero BYOK keys, with keys — actually render blank,
 * but *any* uncaught render exception anywhere in the tree, e.g. a card
 * fed a response shape it doesn't defensively handle, previously fell
 * through to that bare default with zero recovery path).
 *
 * This renders inside the same `AppShell` every real screen uses, so the
 * nav rail stays usable — a crash on one screen no longer strands the user
 * on what looks like a dead page; they can still navigate elsewhere or
 * retry. `reset()` re-renders the failed route without a full page reload.
 */
export function RouteErrorFallback({ error, reset }: ErrorComponentProps) {
  const message = error instanceof Error ? error.message : String(error);

  return (
    <AppShell>
      <div className="p-8">
        <Card>
          <CardHeader>
            <CardTitle>Something went wrong</CardTitle>
            <CardDescription>
              This page hit an unexpected error while rendering. Your data is safe — this is a
              display problem, not a data-loss one.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="rounded-control border border-line bg-paper-soft p-3 font-mono text-12 text-ink-soft">
              {message}
            </p>
            <div className="flex gap-3">
              <Button type="button" variant="primary" onClick={reset}>
                Try again
              </Button>
              <Button type="button" variant="secondary" onClick={() => window.location.assign("/")}>
                Go to Pipelines
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
