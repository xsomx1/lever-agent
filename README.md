# Lever Hiring Agent

A personal command-line agent for my own hiring at Xsolla: it keeps my slice of the Lever
pipeline honest and does the first pass of candidate screening. Single user — me.

Not a shared service, not a platform. A tool I run.

## Status

Epic 0 (bootstrap), Epic 1 (digest), Epic 2 (screening), and Epic 3 (writing back) are done.
`uv run lever digest` flags stale candidates and unhealthy postings and shows day-over-day
movement, on its own schedule (`launchd`, Mon–Fri 11:00 MSK). `uv run lever screen
<posting_id>` scores a candidate's resume against the posting's rubric with Claude
(`claude-sonnet-5` by default — a deliberate cost decision, see
[ADR-0003](docs/adr/0003-claude-opus-5-native-pdf.md)'s amendment) and, with `--post-notes`,
writes the score back to Lever as a note plus a `screened` tag. `lever advance` moves a
candidate's stage with an interactive confirmation — live-verified with a real round-trip
move (`New applicant` → `Recruiter Scheduling Interview` → `New applicant`). `lever audit`
shows the local write history. T0.7 is answered: Thomas Hansen confirmed no vendor
integration owns "AI Screened" (the `screened.io` hypothesis was ruled out) — it's used
manually by some HR/hiring managers, so it's now an ordinary stage-move target like any
other. Every task through Epic 3 is closed. Epic 4 (interview scheduling) is next, if it
turns out to be worth building at all — its own T4.1 has to check first.

Repo: [github.com/xsomx1/lever-agent](https://github.com/xsomx1/lever-agent) (private) ·
branch: `feature/lever-automation-agent`

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
| [0003](docs/adr/0003-claude-opus-5-native-pdf.md) | Native PDF input and structured outputs — no text-extraction library. Default model amended 2026-08-18 to `claude-sonnet-5` (was Opus 5) as a deliberate cost decision |
| [0004](docs/adr/0004-local-state-sqlite.md) | Local SQLite for state; no candidate PII persisted |
| [0005](docs/adr/0005-postings-mine-includes-hiring-manager.md) | "My postings" also includes postings where I'm the hiring manager, not just owner/follower |

## What it will do

**Pipeline hygiene** — stale candidates past a per-stage SLA, postings with no movement,
published postings that should have been closed. A digest I can read in the morning.

**Screening** — pull the resume PDF for a candidate on one of my postings, score it against
that posting's rubric with Claude, and rank the cohort (`uv run lever screen <posting_id>`).
`--post-notes` writes the score back as a Lever note plus a `screened` tag.

**Writing back** — `lever advance <opportunity_id> <stage>` moves one candidate at a time,
with an interactive confirmation and `--dry-run` on every write path. No automated rejection,
hire, or candidate email exists anywhere in this tool (ADR-0002).

**Scoped to my own hiring** — postings where I'm the owner, a follower, or the hiring manager
(ADR-0005), not all 185.

## Access

I hold a Lever API key with the read and write scopes for postings, requisitions,
opportunities, notes, tags, stages, archive state, interviews, panels, feedback, and
webhooks. It authenticates as me, so everything the agent does is attributed to me.

The key lives in the macOS Keychain, never in the repo or a `.env` file. See
[docs/PLAN.md](docs/PLAN.md) T0.3.
