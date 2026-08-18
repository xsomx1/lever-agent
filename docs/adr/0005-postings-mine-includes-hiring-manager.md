# ADR-0005 — "My postings" also includes hiring-manager assignment

**Status:** accepted · **Date:** 2026-08-18

## Context

T0.5 originally scoped "my postings" (the set the digest and, later, screening operate on)
to postings where I'm the `owner` or a `follower`. That was the obvious reading of "postings
I hire for" at the time, and it's what `docs/PLAN.md` T0.5 and `README.md` described.

The real question this closes: **can this agent see a posting that a different account
created and owns, if that account adds me as the `hiringManager` without also adding me as
owner or follower?** Under the original filter, no — that posting would be invisible to
`get_my_postings()`, even though "hiring manager" is a legitimate, common way to be
responsible for a hire in Lever.

Checked against the live API 2026-08-18 before deciding:
- The `Posting` object carries a `hiringManager` field, distinct from `owner`/`followers`.
  Passing `expand=hiringManager` returns the full user object, the same shape as `owner` and
  `followers` — unexpanded, it's a plain UID string.
- Right now, across all 191 postings visible to this key, **zero** have me as `hiringManager`
  without also having me as owner or follower — so today's behavior is unaffected either way.
  But the gap was real: if a colleague ever creates a posting and assigns me as hiring
  manager, the agent would have silently missed it.

## Decision

**`get_my_postings()` matches owner, follower, OR hiring manager** — any one of the three is
enough. `expand` now requests `hiringManager` alongside `owner` and `followers`, and the
matching logic (`_is_mine()` in `src/lever_agent/lever_client.py`) checks all three, handling
`hiringManager` in both its expanded (dict) and unexpanded (plain UID string) shapes.

## Consequences

**Good.** "My postings" now matches the intuitive, complete definition of "postings I'm
responsible for hiring on" — closer to what a recruiter or hiring manager would actually mean
by that phrase. No behavior change today (still exactly 3 postings), so nothing downstream
(digest, and later screening) needs to change to absorb this — it's a pure widening of the
input set, verified with a regression test (`tests/test_distribution_channel.py`) covering
both the expanded-object and plain-string shapes.

**Costs.** None identified. `hiringManager` doesn't grant any additional Lever API
permissions beyond what this key already has — it only changes which postings this agent's
read-only queries surface, not what it's allowed to do with them. The existing write
guardrails (ADR-0002, human-in-the-loop) are unaffected.

**Revisit if:** a posting ever needs to be *excluded* despite one of these three roles being
set — e.g. a posting I'm nominally hiring-manager-on but have handed off entirely. No such
case exists today; if one appears, it'll need an explicit exclusion list rather than
narrowing this definition back down.
