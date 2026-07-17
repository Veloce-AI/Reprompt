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
| `ponytail/`, `ponytail-audit/`, `ponytail-debt/`, `ponytail-gain/`, `ponytail-help/`, `ponytail-review/` | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | MIT | All 6 skills, full directories. "Write minimal necessary code" discipline (skip unneeded code → reuse → stdlib → native → dependency → one-liner → minimum viable, in that order) — directly matches this project's own standing "Simplicity First / No Laziness" instruction. |
| `code-simplifier/` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official), `plugins/code-simplifier` | Apache 2.0 | Full plugin (`agents/code-simplifier.md`, `.claude-plugin/plugin.json`, its own `LICENSE`). Distinct from `anthropics/claude-code` (all-rights-reserved, checked separately) — `claude-plugins-official` is a different, genuinely Apache-2.0 Anthropic repo. |

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

**Second round, also checked**: `lak7/devildev` (Apache 2.0, but a whole
standalone Next.js/Prisma SaaS app, not a skill — nothing shaped like a
portable instruction set to pull, regardless of license); `enuno/claude-
command-and-control` (no LICENSE file anywhere in the repo — default
copyright means all-rights-reserved, not pulled, though its `docs/best-
practices/` looked like genuinely useful multi-agent-orchestration reading
if a license ever gets added); `getdesign.md` (a web catalog service,
nothing downloadable); `OpenHands/OpenHands` (a whole self-hosted agent
platform, not a skill); `msitarzewski/agency-agents` (a library of agent
personas for other tools, not `SKILL.md` format); `elder-plinius/T3MP3ST`
(checked specifically because that account is known for jailbreak/prompt-
injection content — turned out to be a legitimate authorized-pentesting
framework, not adversarial, but has zero relevance to a prompt-optimization
product regardless — skipped on relevance, not safety, grounds).
`modelcontextprotocol/servers`' `sequentialthinking` server is a real,
useful, official MIT-licensed MCP server — but it's a different artifact
type (a running server configured as an MCP connector), not a file that
belongs in this skills folder; worth knowing about, not pullable here.

If a future session wants to pull from a new external repo, follow the same
process: find the actual `LICENSE` file (not a README badge — verify the
real file), confirm it's a permissive license (MIT/Apache/BSD), only then
copy, and add a row to the table above.
