# Lessons

## M0 - ParityBeam draw-in animation and drawer direction (opencode build, caught by review)

`ParityBeam`'s `animateIn` prop animated the marker instead of the beam
track, used a shared global `<style>` class (so multiple instances on one
page fought over a single hardcoded delay), and its keyframe clobbered the
marker's centering `transform`. Separately, the stage drawer opened from
the bottom instead of the right because `vaul`'s `Root` defaults to
`direction="bottom"` and nothing overrode it. Neither bug was caught by
the passing test suite - both were in code paths the tests didn't
exercise (animation, drawer direction specifically). Fixed by animating a
dedicated beam-track wrapper via inline-style `clip-path` transitions
(no shared class, no shared transform), and defaulting `DrawerRoot` to
`direction="right"`. Lesson: a green test suite only proves what it
actually asserts - budget for a second pass that reads the untested
branches, not just the covered ones.

## M0 - root route always rendered Home regardless of URL

`router.tsx`'s root route component was hardcoded to `<Home />` instead of
`<Outlet />`, so every route (including `/dev/kit`) rendered the home page.
Found via Playwright, not by inspection - the h1 assertion failed with
"Reprompt" instead of the expected page title. Fixed by rendering
`<Outlet />` at the root. Lesson: an e2e test that actually navigates and
asserts on rendered content catches routing bugs that unit tests and
manual code review both missed.

## M1.5 - StrictMode + @tanstack/react-query mutations get stuck on "pending"

On `@tanstack/react-query@5.101.2` (latest at the time), wrapping the app
in `<StrictMode>` caused `useMutation`'s `onSuccess`/`onSettled` callbacks
to fire correctly (confirmed via console + network instrumentation - the
POST completed with 201, the callbacks ran, `queryClient.invalidateQueries`
happened) while the *component's own* `importMutation.status` stayed
`"pending"` forever, so the UI never left the loading state. Root cause
is believed to be StrictMode's dev-only mount -> effect -> cleanup ->
effect-again cycle interacting badly with the mutation observer's
subscribe/unsubscribe timing - the observer's internal cache updates, but
the currently-rendered component's subscription misses the final
notification. Confirmed by removing `<StrictMode>` alone: the exact same
flow then transitions `idle -> pending -> success` correctly every time.

Separately (and still needed even with StrictMode removed): a file
dropped on the Pipelines home empty state is handed to the Import wizard
route via a small Zustand store and picked up in a `useEffect`. That
effect is guarded with a `useRef` flag, not just a state check - a
state-based guard (`!selectedFile`) doesn't work under StrictMode's
double-invoke because both invocations run against the *same* render's
closure before any state update from the first invocation is visible, so
`!selectedFile` reads `true` both times and the mutation fires twice
(confirmed as the cause of a duplicate-import bug before the ref guard
was added).

Lesson: StrictMode's double-invoke behavior is not just a "run twice, no
side effects, no big deal" diagnostic in practice - it can genuinely break
third-party hook state, and effects with non-idempotent side effects
(mutations, anything with a ref-based "have I already started this"
check) need a ref guard, not a state guard, since state updates aren't
visible across StrictMode's double-invoke within the same render pass.
Removing StrictMode is a legitimate call here (it's dev-only, zero
production impact) rather than working around a library-level interaction
bug indefinitely - but the ref-guard pattern is worth keeping as the
default for any future effect with a mutating side effect, StrictMode or
not.
