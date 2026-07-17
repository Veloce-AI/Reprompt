# Skill sources and attribution

This project's `.claude/skills/` folder mixes two kinds of skills. Keep this
file accurate whenever a skill is added, removed, or updated — it's the
record of what's ours vs. pulled from elsewhere, and under what terms.

## Written for Reprompt (no external source)

- `saas-product-design/` — empty-state/discoverability/live-status discipline,
  written directly from bugs found in this project's own history.
- `frontend-design/` — Reprompt's own visual identity discipline (tokens,
  motion-means-something, typography hierarchy).
- `system-design/` — architecture principles specific to this project's
  headless-core / additive-schema / harness-vs-target-model split.

## Pulled from external repos (permissively licensed, verified before copying)

| Skill | Source | License | What was pulled |
|---|---|---|---|
| `impeccable/` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | Apache 2.0 | Full skill directory (`SKILL.md`, `reference/`, `scripts/`) — self-contained by design, includes original `LICENSE` + `NOTICE.md`. |
| `design-system/` | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | MIT | `SKILL.md` + the token/component reference docs only. Skipped: slide-generation CSVs/scripts (irrelevant to Reprompt, not a presentation tool). Original `LICENSE` included. |
| `ui-styling/` | same repo, `ui-styling` skill | MIT (repo LICENSE) / OFL (individual fonts, not pulled) | `SKILL.md` + shadcn/Tailwind reference docs only. Skipped: ~70 embedded font binaries and their per-font `-OFL.txt` files (each under SIL Open Font License, irrelevant — Reprompt has its own type choices) and the Python shadcn/tailwind scripts (avoid adding a Python runtime dependency for this). |
| `frontend-design-anthropic/` | [anthropics/skills](https://github.com/anthropics/skills), `skills/frontend-design` | Apache 2.0 | Full skill (`SKILL.md` + `LICENSE.txt`). Renamed folder + frontmatter `name` from `frontend-design` to `frontend-design-anthropic` to avoid colliding with our own project-specific `frontend-design/` skill — both are legitimately useful and distinct (ours is Reprompt-tokens-specific, this one is general-purpose bold-interface guidance). |
| `theme-factory/` | same repo, `skills/theme-factory` | Apache 2.0 | Full skill (`SKILL.md`, `LICENSE.txt`, `theme-showcase.pdf` reference). |
| `webapp-testing/` | same repo, `skills/webapp-testing` | Apache 2.0 | Full skill — Playwright-based web app testing guidance, directly applicable given how many bugs this project has caught by actually driving the app instead of trusting unit tests alone. |
| `skill-creator/` | same repo, `skills/skill-creator` | Apache 2.0 | Full skill — meta-skill for writing better skills, useful when this project needs to author more of its own. |

**Explicitly NOT pulled, checked and rejected**: `anthropics/claude-code`'s
`frontend-design` plugin — its `LICENSE.md` is "All rights reserved,
subject to Anthropic's Commercial Terms of Service," not an open license.
Copying it would be a real license violation, not a gray area — don't
revisit this without Anthropic's explicit permission. `nexu-io/open-design`
was checked (Apache 2.0, permissive) but its only skill (`od-contribute`) is
about contributing skills to their own project, not a usable design skill —
nothing pulled from it. `anthropics/skills`' own `canvas-design` (Apache
2.0, but about generating static poster/art PNGs/PDFs — a different meaning
of "canvas" than this project's DAG view, not relevant) and `claude-api`
(Apache 2.0, but this exact skill is already available as a first-class
built-in skill in every Claude Code session — pulling a copy into the repo
would just be a stale duplicate) were checked and deliberately skipped.
`docx`/`pdf`/`pptx`/`xlsx` in that same repo are explicitly marked
"source-available, not open source" in its README — not pulled, and don't
revisit without actually reading their specific terms first.

If a future session wants to pull from a new external repo, follow the same
process: find the actual `LICENSE` file (not a README badge — verify the
real file), confirm it's a permissive license (MIT/Apache/BSD), only then
copy, and add a row to the table above.
