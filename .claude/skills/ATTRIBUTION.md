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

**Explicitly NOT pulled, checked and rejected**: `anthropics/claude-code`'s
`frontend-design` plugin — its `LICENSE.md` is "All rights reserved,
subject to Anthropic's Commercial Terms of Service," not an open license.
Copying it would be a real license violation, not a gray area — don't
revisit this without Anthropic's explicit permission. `nexu-io/open-design`
was checked (Apache 2.0, permissive) but its only skill (`od-contribute`) is
about contributing skills to their own project, not a usable design skill —
nothing pulled from it.

If a future session wants to pull from a new external repo, follow the same
process: find the actual `LICENSE` file (not a README badge — verify the
real file), confirm it's a permissive license (MIT/Apache/BSD), only then
copy, and add a row to the table above.
