# External tools & systems (not skills — run standalone, not read as instructions)

Everything else in `.claude/skills/` is a `SKILL.md` Claude reads and
applies while working *inside* this repo. The tools below are different in
kind: whole separate systems you run on their own, outside this workflow,
for a specific job. Don't try to fold these into the skills folder as
instruction files — there's nothing to "read," they're software you
operate. Listed here so the option is documented and discoverable, not
because any of them are currently set up or in active use.

## Architecture/spec drafting — `devildev`

[lak7/devildev](https://github.com/lak7/devildev) (Apache 2.0) — a
standalone Next.js/Prisma spec-driven architecture app. Its actual
*methodology* (evidence-based, business-focused architecture write-ups,
banning hypothetical components) was extracted into this project's own
`spec-driven-planning` skill instead of running the tool itself — that
gets the useful part without standing up a second application.

If ever wanted as a running tool (not just its methodology): `git clone`
it elsewhere, `npm install && npm run dev`, and use it standalone to draft
architecture specs before a big feature (e.g. the planned LLM-telemetry/
scorecard work) — output would be reference material to inform a
Reprompt-side plan, not something integrated or imported back in.
Not set up. Nobody's asked for it as a running tool yet.

## Security testing — `T3MP3ST`

[elder-plinius/T3MP3ST](https://github.com/elder-plinius/T3MP3ST) — an
authorized-penetration-testing framework that coordinates AI agents
across an offensive-security "kill chain." Checked carefully given that
GitHub account's separate, unrelated reputation for jailbreak/prompt-
injection content (`L1B3RT4S` etc.) — T3MP3ST itself is legitimate,
requires explicit written authorization to target anything, and enforces
scope boundaries. Not relevant to Reprompt's own skills folder (it's a
pentesting tool, not a coding-assistant skill), but a legitimate future
option: run it as a fully separate, standalone tool against Reprompt's
own *deployed* instance for actual authorized security testing — nothing
gets combined or distributed, so no licensing entanglement with this
codebase either way. Not set up. Only relevant once there's a real
deployed instance worth testing.

## Research-only, not a tool to run — `OpenHands`

[OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) — a full,
competing self-hosted AI coding agent platform (its own Agent Canvas UI,
Agent Server, automation server). Not something to install alongside
Claude Code — there's no "use it within this workflow." The honest
answer is "read its architecture for ideas" (research), not integration.
Not pursued — noted here so nobody re-investigates it expecting a
different conclusion.
