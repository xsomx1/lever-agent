# Lever Hiring Agent

A personal command-line agent for my own hiring at Xsolla: it keeps my slice of the Lever
pipeline honest and does the first pass of candidate screening. Single user — me.

Not a shared service, not a platform. A tool I run.

## Status

Planning complete, awaiting go-ahead to build. No code yet.

Branch: `feature/lever-automation-agent` · target repo: a new **private** repo under
[github.com/xsomx1](https://github.com/xsomx1)

## Documents

| Document | What it is |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Epics, tasks, roadmap, dependencies |
| [docs/CONTEXT.md](docs/CONTEXT.md) | Lever API constraints, live pipeline, prior art, open unknowns |
| [docs/adr/](docs/adr/) | The four decisions this rests on |

## The decisions

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-standalone-personal-agent.md) | A standalone personal CLI, not n8n and not the corporate Cloud Run platform |
| [0002](docs/adr/0002-human-in-the-loop.md) | Human-in-the-loop on the reject and hire gates |
| [0003](docs/adr/0003-claude-opus-5-native-pdf.md) | Claude Opus 5 with native PDF input and structured outputs — no text-extraction library |
| [0004](docs/adr/0004-local-state-sqlite.md) | Local SQLite for state; no candidate PII persisted |

## What it will do

**Pipeline hygiene** — stale candidates past a per-stage SLA, postings with no movement,
published postings that should have been closed. A digest I can read in the morning.

**Screening** — pull the resume PDF for a new applicant on one of my postings, score it
against that posting's rubric with Claude, and rank. The score goes back into Lever as a
note; stage moves need my confirmation.

**Scoped to my own hiring** — postings where I'm the owner or a follower, not all 185.

## Access

I hold a Lever API key with the read and write scopes for postings, requisitions,
opportunities, notes, tags, stages, archive state, interviews, panels, feedback, and
webhooks. It authenticates as me, so everything the agent does is attributed to me.

The key lives in the macOS Keychain, never in the repo or a `.env` file. See
[docs/PLAN.md](docs/PLAN.md) T0.3.
