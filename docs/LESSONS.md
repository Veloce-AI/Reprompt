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

## Dev DB silently drifted 4 migrations behind its own `alembic_version` stamp (2026-07-22)

**Symptom**: Migrations tab stuck on "Loading migrations…" forever; a real
screenshot from the product owner. `GET /pipelines/{id}/migrations`
actually 500'd with `sqlalchemy.exc.OperationalError: no such column:
migrations.activity_log` — confirmed by calling the endpoint directly via
`TestClient(app, raise_server_exceptions=True)` to get the real traceback
(the live server only returned a bare "Internal Server Error", no detail).

**Root cause**: `apps/api/src/reprompt_api/main.py`'s dev-convenience
auto-create (`Base.metadata.create_all()`) creates any table *missing
entirely* to match current `models.py` — but it cannot add a *column* to
a table that already exists. At some point this session, the dev DB
(`apps/api/test.db`) had `seam_check_results` and `assertions` (two brand
new tables from later migrations) auto-created this way, which silently
made the app *look* healthy — but `activity_log` (on the pre-existing
`migrations` table) and `holdout_score` (on the pre-existing `candidates`
table) never got added, because auto-create only handles missing tables,
not missing columns. `alembic_version` stayed stamped at `450ae8aefaa7`
(a merge point from early in the session) the entire time — 4 real
migrations behind `alembic heads`' actual `b2c3d4e5f6a7` — with nothing
forcing a mismatch check, so the drift was invisible until a query
happened to touch one of the two missing columns.

**Fix, applied directly to the real dev DB** (not a code change — the
migrations themselves were always correct): added the two missing
columns by hand (`ALTER TABLE migrations ADD COLUMN activity_log JSON`,
`ALTER TABLE candidates ADD COLUMN holdout_score FLOAT`), confirmed the
two auto-created tables' schemas already matched their migrations exactly
(they did), then `alembic stamp head` to make the version pointer honest
again — deliberately not a blind `alembic upgrade head` or a DB
delete-and-recreate, since either risks either an "already exists" error
on the two tables that were already fine, or losing 19MB of real seeded
pipeline/trace data for no reason.

**Lesson**: `main.py`'s auto-create fallback is a documented gotcha
already (see `docs/TESTING.md`'s "Database" step), but this is a sharper
version of it than previously written down — it doesn't just risk a
*later* `alembic upgrade head` failing outright (the previously-documented
case), it can also leave the DB in a **mixed, partially-migrated state**
that looks completely healthy until a request happens to touch the one
column that's actually missing, with no error anywhere until that exact
moment. `alembic current` vs `alembic heads` disagreeing is a real,
checkable health signal that nothing in this project currently checks
automatically. Worth adding to `scripts/dev-restart.ps1`'s existing
"refuse to declare success until proven serving current code" check — it
already tests one class of staleness (a ghost process serving old code),
this is a second, different class (a live, current-code process serving
against a stale schema) that the same script should also catch.
