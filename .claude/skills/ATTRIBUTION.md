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
- `spec-driven-planning/` — evidence-based architecture/spec writing
  discipline. Methodology *inspired by* reading `lak7/devildev`'s
  `prompts/ReverseArchitecture.ts` (Apache 2.0) — the actual approach
  (evidence-over-hypothesis, ban idealized components, map every claim to
  a real file) was rewritten in this project's own words/context rather
  than copied, since the source is prose embedded in application code, not
  a portable instruction file. See `EXTERNAL_TOOLS.md` in this same folder
  for devildev itself (a whole standalone app, not pulled as a skill).

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
| `design-references/` | [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) | MIT | 3 of 70+ `DESIGN.md` entries (Linear, Stripe, PostHog) — hand-picked as the closest category analogs to Reprompt (data-dense dev/analytics SaaS), not a bulk pull. Reference material for comparison, not templates to copy — see the skill's own "What NOT to do" section. |
| `code-reviewer-persona/`, `ai-code-security-auditor/`, `appsec-engineer-persona/` | [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) | MIT | 3 of 230+ agent personas, hand-picked (not a bulk import of all divisions) — `engineering-code-reviewer.md`, `security-ai-generated-code-auditor.md`, `security-appsec-engineer.md`. Frontmatter `name` field adjusted to kebab-case matching this project's folder-naming convention; content otherwise unchanged. `ai-code-security-auditor` is especially relevant given how much of this project's own code has been AI-agent-generated this session. |

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

**Second round — "not skill-format" resolved concretely instead of a flat
reject**: `msitarzewski/agency-agents` (MIT) turned out to have genuinely
useful individual personas once actually read — 3 hand-picked into real
skills above, see the table. `getdesign.md`'s actual content lives at
`VoltAgent/awesome-design-md` (MIT) — 3 hand-picked entries pulled into
`design-references/`, see the table. `lak7/devildev` (Apache 2.0) is still
not something to fold into this skills folder — it's a whole standalone
Next.js/Prisma app, not a portable instruction set, license doesn't change
that. If ever wanted, the honest way to use it is as its own separate
running tool (`git clone` + `npm install && npm run dev` elsewhere) for
drafting architecture specs before a big feature, not as a "skill." Not set
up — nobody's asked for it as an actual running tool yet, just flagging the
option exists. `OpenHands/OpenHands` — same category as devildev, a whole
competing agent framework, not integrable; the honest use is "read its
architecture for ideas" (research), not installation. `elder-plinius/
T3MP3ST` — checked carefully given that account's known jailbreak/prompt-
injection reputation; turned out to be a legitimate authorized-pentesting
framework, not adversarial, but has zero relevance to a prompt-optimization
product's own skills folder. Its one legitimate future use for THIS
project would be running it as a fully separate, standalone tool against
Reprompt's own deployed instance for actual authorized security testing —
not code reuse, nothing combined/distributed, so no licensing entanglement
either way. Not set up, not requested — noting the option only.
`enuno/claude-command-and-control` — still no LICENSE file anywhere in the
repo, still not pulled; its `docs/best-practices/` remains genuinely
interesting multi-agent-orchestration reading if a license ever gets
added. `modelcontextprotocol/servers`' `sequentialthinking` server is a
real, useful, official MIT-licensed MCP server — but it's a different
artifact type (a running server configured as an MCP connector), not a
file that belongs in this skills folder; worth knowing about, not
pullable here.

If a future session wants to pull from a new external repo, follow the same
process: find the actual `LICENSE` file (not a README badge — verify the
real file), confirm it's a permissive license (MIT/Apache/BSD), only then
copy, and add a row to the table above.
