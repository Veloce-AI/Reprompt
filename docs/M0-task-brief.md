# Task brief: Refract M0 — Scaffold + design system

You are building milestone **M0 only** for Refract, a model-migration parity engine. Before writing any code, read these two files fully — they are the source of truth for product context and design rules:

- `docs/refract-master-build-prompt.md` (esp. §1 working rules, §2 stack, §3 design system, §5 M0 definition)
- `docs/refract-parity-engine-plan.md` (product context)

**Scope guard:** M0 is scaffold + design system only. Do NOT build data models, ingest, rubrics, optimizers, Celery workers, auth, or any M1–M5 feature. When M0 is done, STOP for human review of the `/dev/kit` page in a browser.

**Environment:** Windows 11 host. Repo is at `C:\VeloceAI\Refract` — a freshly initialized git repo containing only `docs/`. Use conventional commits, one logical change per commit. Monorepo tooling: pnpm workspaces for JS, uv for Python 3.12.

---

## 1. Exact file tree to create

```
refract/
├── .gitignore                          # node_modules, dist, .venv, __pycache__, .env, *.pyc
├── .env.example                        # compose vars (postgres creds, langfuse secrets) — no real secrets
├── package.json                        # root; private; scripts: dev, build, test delegating to apps/web
├── pnpm-workspace.yaml                 # packages: ["apps/*", "packages/*"]
├── docs/
│   ├── refract-master-build-prompt.md  # exists — do not modify
│   ├── refract-parity-engine-plan.md   # exists — do not modify
│   └── LESSONS.md                      # create empty log (per working rule 5): "# Lessons" header only
├── infra/
│   ├── docker-compose.yml              # services: postgres:16, redis:7, langfuse (v2 image)
│   └── postgres-init.sql               # creates two databases: refract, langfuse
├── apps/
│   ├── api/
│   │   ├── pyproject.toml              # uv project; deps: fastapi, uvicorn[standard]; dev: pytest, httpx
│   │   ├── src/
│   │   │   └── refract_api/
│   │   │       ├── __init__.py
│   │   │       └── main.py             # FastAPI app; GET /health -> {"status": "ok"}
│   │   └── tests/
│   │       └── test_health.py          # TestClient asserts 200 + body
│   └── web/
│       ├── package.json                # react 18, vite, typescript, tailwind, @tanstack/react-router,
│       │                               # @fontsource/spectral, @fontsource/ibm-plex-sans, @fontsource/ibm-plex-mono,
│       │                               # shadcn deps (radix, cva, clsx, tailwind-merge, vaul for drawer),
│       │                               # dev: vitest, @testing-library/react, playwright
│       ├── index.html
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── tailwind.config.ts          # maps Tailwind theme to the CSS variables in tokens.css
│       ├── postcss.config.js
│       ├── components.json             # shadcn config
│       ├── playwright.config.ts
│       ├── e2e/
│       │   └── kit.spec.ts             # smoke: /dev/kit renders, ParityBeam visible
│       └── src/
│           ├── main.tsx                # imports fonts + styles, mounts router
│           ├── router.tsx              # TanStack Router, code-based route tree: "/" and "/dev/kit"
│           ├── routes/
│           │   ├── home.tsx            # placeholder page ("Refract" title + link to /dev/kit)
│           │   └── dev-kit.tsx         # the design-system demo page (see §4 below)
│           ├── styles/
│           │   ├── tokens.css          # LITERAL contents in §2 below — copy exactly
│           │   └── globals.css         # tailwind directives; body bg --paper, color --ink, font --font-sans;
│           │                           # focus-visible ring 2px --beam; imports tokens.css first
│           ├── lib/
│           │   └── utils.ts            # cn() helper
│           └── components/
│               ├── ui/
│               │   ├── button.tsx      # shadcn, restyled via tokens
│               │   ├── card.tsx
│               │   ├── table.tsx
│               │   ├── badge.tsx
│               │   └── drawer.tsx
│               └── parity-beam.tsx     # ParityBeam component (API in §3) + exported parityStatus() helper
└── packages/
    └── core/
        ├── pyproject.toml              # uv project, name refract-core; zero FastAPI imports — engine lives here later
        ├── src/
        │   └── refract_core/
        │       └── __init__.py         # __version__ = "0.0.1" only; no engine code in M0
        └── tests/
            └── test_placeholder.py     # trivial import test so pytest passes
```

Notes on the tree:
- **Fonts are self-hosted via @fontsource** (Spectral 600; IBM Plex Sans 400/500/600; IBM Plex Mono 400/500) — no Google Fonts CDN link, keeps the future on-prem story clean.
- **No Dockerfiles for api/web in M0.** docker-compose runs only the backing services (postgres, redis, langfuse); api and web run locally via `uv run uvicorn` and `pnpm dev`. Dockerfiles come in a later milestone.
- Langfuse v2 needs `DATABASE_URL` (pointing at the `langfuse` db), `NEXTAUTH_SECRET`, `SALT`, `NEXTAUTH_URL` — wire these through `.env.example` with placeholder values. Expose langfuse on :3001 (web dev server will use :3000 or Vite's default :5173), api on :8000, postgres :5432, redis :6379.

## 2. `apps/web/src/styles/tokens.css` — full literal contents

Copy this file exactly as written:

```css
/* ============================================================
   Refract design tokens — "Instrument Grade"
   Source of truth: docs/refract-master-build-prompt.md §3.
   Everything in the UI derives from these variables.
   Do not use raw hex or px values in components — token it.
   ============================================================ */

:root {
  /* ---- Color: light "laboratory" theme (default) ---- */
  --paper: #FAFBFD;        /* cool near-white, main bg */
  --ink: #10182B;          /* deep blue-black, primary text */
  --ink-soft: #5A6478;     /* secondary text, labels */
  --line: #E3E8F0;         /* hairline borders, 1px — used instead of shadows */
  --beam: #4C5FE8;         /* refraction indigo — actions, links, focus rings, active nodes */
  --beam-soft: #EDEFFE;    /* indigo tint for selected/hover surfaces */

  /* Parity semantics — fixed meanings, never decorative */
  --parity-pass: #0E9F6E;
  --parity-near: #D97706;
  --parity-fail: #DC2626;

  /* Spectrum gradient (violet -> indigo -> teal)
     Reserved EXCLUSIVELY for the ParityBeam component.
     Note: spec names the hues but not hex values for violet/teal;
     indigo is anchored to --beam. Violet/teal below are the only
     two interpreted values in this file — flag at review. */
  --spectrum-violet: #8B5CF6;
  --spectrum-indigo: var(--beam);
  --spectrum-teal: #14B8A6;
  --spectrum: linear-gradient(
    90deg,
    var(--spectrum-violet) 0%,
    var(--spectrum-indigo) 50%,
    var(--spectrum-teal) 100%
  );

  /* ---- Type ---- */
  --font-display: "Spectral", Georgia, serif;         /* SemiBold only; page titles, big scorecard
                                                         numbers, empty-state headlines; max ~2/screen */
  --font-sans: "IBM Plex Sans", system-ui, sans-serif; /* UI/body, weights 400/500/600 */
  --font-mono: "IBM Plex Mono", ui-monospace, monospace; /* prompts, diffs, tokens, code;
                                                            all table numerals via tabular-nums */

  /* Scale: 12 / 13 / 14 (base) / 16 / 20 / 28 / 40 */
  --text-12: 12px;
  --text-13: 13px;
  --text-14: 14px;   /* base */
  --text-16: 16px;
  --text-20: 20px;
  --text-28: 28px;
  --text-40: 40px;

  --weight-regular: 400;
  --weight-medium: 500;
  --weight-semibold: 600;

  /* Dense but breathable: small data type earns generous line-height */
  --leading-normal: 1.5;
  --leading-display: 1.2;

  /* ---- Layout: 4px spacing grid ---- */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;

  --radius-card: 6px;
  --radius-control: 4px;

  --nav-rail-width: 220px;   /* left nav rail: icons + labels */
  --content-max-width: 1440px;

  /* Depth via hairlines + tints, not drop shadows.
     One shadow level allowed, for popovers ONLY: */
  --shadow-popover: 0 4px 16px rgba(16, 24, 43, 0.10);

  /* Keyboard focus: visible 2px --beam ring */
  --focus-ring: 0 0 0 2px var(--beam);

  /* ---- Motion: 150–200ms ease-out, state changes only ---- */
  --duration-fast: 150ms;
  --duration-base: 200ms;
  --ease-out: cubic-bezier(0, 0, 0.2, 1);
  --beam-stagger: 60ms;      /* scorecard beams draw-in stagger */

  /* ---- ParityBeam geometry ---- */
  --beam-thickness: 3px;
}

@media (prefers-reduced-motion: reduce) {
  :root {
    --duration-fast: 0ms;
    --duration-base: 0ms;
    --beam-stagger: 0ms;
  }
}
```

Wire `tailwind.config.ts` so Tailwind utilities resolve to these variables (e.g. `colors: { paper: "var(--paper)", ink: "var(--ink)", ... }`, `borderRadius: { card: "var(--radius-card)", control: "var(--radius-control)" }`, font families, and the 12–40 font-size scale). Components must never hardcode hex/px that a token covers.

## 3. ParityBeam component API

File: `apps/web/src/components/parity-beam.tsx`. This is the signature element — the one memorable thing in the UI. Spec (master prompt §3): a thin 3px horizontal beam; benchmark side is a solid `--ink` line; at the "prism" midpoint it refracts into the spectrum gradient; the candidate's parity score is a marker positioned along it, colored by parity semantics. Same component everywhere.

```ts
export type ParityStatus = "pass" | "near" | "fail";

/** Maps a 0–100 score to parity semantics.
 *  pass: score >= passThreshold (default 95)
 *  near: score >= nearThreshold (default 80)
 *  fail: otherwise
 *  Exported separately so badges/chips reuse the same mapping. */
export function parityStatus(
  score: number,
  passThreshold?: number, // default 95
  nearThreshold?: number  // default 80
): ParityStatus;

export interface ParityBeamProps {
  /** Candidate parity score, 0–100. Positions the marker along the beam
   *  (marker left = score% of track width) and drives its color via
   *  parityStatus(). Omit for the "no migration yet" state. */
  score?: number;

  /** Optional cost figure rendered as a small mono label at the beam's
   *  right end (e.g. "$0.42/1k"). Preformatted string; the beam does
   *  no currency logic. */
  cost?: string;

  /** Parity thresholds; defaults 95 / 80 per product defaults. */
  passThreshold?: number;
  nearThreshold?: number;

  /** Prism position along the track, 0–1. Default 0.5.
   *  Left of the prism: solid var(--ink) benchmark line.
   *  Right of the prism: var(--spectrum) gradient. */
  prismPosition?: number;

  /** Show the numeric score (e.g. "96.4%") beside the marker, in
   *  --font-mono tabular-nums. Default false. */
  showLabel?: boolean;

  /** Draw the beam in left-to-right on mount (var(--duration-base),
   *  var(--ease-out)) — for the scorecard's orchestrated moment.
   *  Must respect prefers-reduced-motion (tokens already zero the
   *  durations). Default false. */
  animateIn?: boolean;

  /** Delay before animateIn starts, for staggering sibling beams by
   *  var(--beam-stagger) (60ms). Milliseconds. Default 0. */
  animateDelay?: number;

  className?: string;
}
```

Rendering/behavior requirements:

- **Anatomy:** full-width track, height `var(--beam-thickness)` (3px). Two segments split at `prismPosition`: solid `var(--ink)`, then `var(--spectrum)`. A small subtle prism notch/diamond at the split point is allowed but optional. Marker: a small dot (~8px) vertically centered on the track at `score%`, filled with `var(--parity-pass|near|fail)`; give it a 2px `var(--paper)` outline so it reads on top of the gradient.
- **States:**
  1. `score` provided → full beam + marker (pass / near / fail color).
  2. `score` undefined → benchmark-only state: solid `--ink` line at reduced opacity (~0.35), no gradient, no marker.
  3. `animateIn` → beam scales/clips in left-to-right once on mount.
- **Accessibility:** `role="meter"` with `aria-valuenow={score}`, `aria-valuemin={0}`, `aria-valuemax={100}`, and an `aria-label` like `"Parity score 96.4%"`; the no-score state uses `aria-label="No migration yet"` with `role="img"`.
- The spectrum gradient must not be used anywhere else in the app — this component owns it.
- Unit tests (Vitest): `parityStatus` boundary cases (79.9/80/94.9/95/100), marker color class per state, no-marker render when `score` is undefined.

## 4. `/dev/kit` demo page

A single scrollable page (Storybook-style, but hand-rolled — do not add Storybook) with labeled sections. All copy in sentence case; buttons say what happens (never "Submit"):

1. **Color** — swatch grid for every color token (name, hex, sample), spectrum gradient bar, parity trio labeled with their fixed meanings.
2. **Type** — the full 12–40 scale in Plex Sans; a Spectral SemiBold display specimen ("Parity 96.4%"); a Plex Mono block with tabular-nums digits.
3. **Button** — primary (`--beam`), secondary/outline (hairline `--line`), ghost, destructive (`--parity-fail`), disabled; radius 4px; visible focus ring on tab.
4. **Card** — 6px radius, 1px `--line` border, no shadow; one card with a `--beam-soft` selected state.
5. **Table** — sample pipeline-shaped data (name, stages, model badges, parity), numerals in mono tabular-nums, hairline row dividers.
6. **Badge** — model badges (neutral) and parity badges (pass/near/fail using parity tokens).
7. **Drawer** — right-side drawer (this becomes the stage drawer later); opens on button click, closes on esc/overlay.
8. **ParityBeam** — the centerpiece: pass (96.4), near (87.2), fail (61.0), no-score, with-label + cost variant, and a "replay draw-in" button demonstrating three stacked beams animating with 60ms stagger.

## 5. Acceptance criteria (all must pass before you stop)

- [ ] `pnpm install` succeeds at repo root; `uv sync` succeeds in `apps/api` and `packages/core`.
- [ ] `docker compose -f infra/docker-compose.yml up -d` starts postgres, redis, and langfuse; langfuse UI reachable on its port; no crash-looping containers.
- [ ] `uv run uvicorn refract_api.main:app` serves; `GET /health` returns 200 `{"status": "ok"}`; `uv run pytest` passes in `apps/api` and `packages/core`.
- [ ] `pnpm dev` in `apps/web` serves; `/dev/kit` renders every section in §4 with zero console errors.
- [ ] ParityBeam shows all states listed above; marker color follows parity semantics; draw-in animation works and is disabled under `prefers-reduced-motion`.
- [ ] Vitest passes (ParityBeam tests included); Playwright smoke test passes (`/dev/kit` loads, beam visible, drawer opens).
- [ ] **No shadcn default look:** fonts are Spectral/Plex (not Inter), radii are 6px/4px, borders are 1px `--line` hairlines, no drop shadows anywhere except the popover token. Audit each component against §3 of the master prompt.
- [ ] Tabbing through the kit page shows a visible 2px `--beam` focus ring on every interactive element; text meets WCAG AA contrast on `--paper`.
- [ ] Page is usable at 1280px width.
- [ ] `tokens.css` matches §2 of this brief byte-for-byte in values; no component hardcodes a hex/px value a token covers.
- [ ] Work is committed with conventional commits, one logical change each (e.g. `chore: scaffold monorepo`, `feat(infra): docker-compose services`, `feat(api): healthcheck`, `feat(web): design tokens and fonts`, `feat(web): restyled shadcn primitives`, `feat(web): ParityBeam component`, `feat(web): /dev/kit demo page`).

**Stop-gate:** when all boxes are checked, STOP. Post a short summary (what was built, how to run it, test results) and wait for human review of `/dev/kit` in a browser. Do not begin M1.
