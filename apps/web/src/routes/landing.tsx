// Minimal placeholder for the marketing landing page at "/". Real content
// (copy, visuals, etc.) is Phase 1 of the landing-page plan - this phase is
// routing plumbing only (see DEV_TRACKER.md). Signed-in visitors never see
// this: router.tsx's landingRoute redirects them to /pipelines in
// beforeLoad before this component ever renders.
export default function Landing() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="font-display text-40 font-semibold leading-display text-ink">Reprompt</h1>
      <p className="text-14 text-ink-soft">Migrate AI pipelines between models with confidence.</p>
    </div>
  );
}
