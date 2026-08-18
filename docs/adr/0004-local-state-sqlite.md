# ADR-0004 — Local SQLite for state, no candidate PII persisted

**Status:** accepted · **Date:** 2026-08-18

## Context

The agent needs to remember things between runs: screening scores, pipeline snapshots for
day-over-day deltas, and an audit log of what it wrote back to Lever.

Every existing Lever automation at Xsolla writes to the Neuronet Neo4j graph, because they
feed a company-wide knowledge base that other systems query. This agent has no such
consumer — it is a single-user tool, and its state is read by nothing but itself.

The data question matters more than the storage question. Lever holds 6,100 candidates'
personal data under GDPR. The API key can download any of their resumes. Anything this tool
persists is a new copy of that data, outside Lever's retention and deletion controls — and
Lever has no delete-my-data endpoint, so propagating a deletion would be on me.

## Decision

**SQLite, local, via the stdlib `sqlite3` module.** One file on my machine.

**No candidate PII is persisted.** Specifically:

- Resume bytes are held **in memory only** — never written to disk, never logged, never cached.
- What gets stored is the **score, the reasoning, and the Lever opportunity ID**. The ID is
  the pointer; Lever stays the system of record for the person.
- Pipeline snapshots store counts and stage IDs, not names.
- The audit log stores what changed, when, and the score behind it.

## Consequences

**Good.** No database to run. No server, no credentials, no network dependency. Trivially
inspectable with `sqlite3` when something looks wrong, and trivially deleted. Keeping PII out
means the tool never becomes a shadow copy of the ATS or a GDPR obligation of its own.

**Costs.** State lives on one machine, so a laptop rebuild loses the history — acceptable,
since everything meaningful is reconstructable from Lever. No cross-machine access. If this
ever moves to the corporate platform, this decision gets revisited alongside ADR-0001, since
the graph is where shared state belongs there.

**Discipline required.** "No PII" is a property that has to be actively maintained, not a
one-time choice — the easy mistake is logging a resume for debugging. Anything that touches
resume bytes needs checking that it does not persist them, and `.gitignore` covers the
database file.

**Revisit if:** the tool goes multi-user or multi-machine, both of which mean ADR-0001 is
being revisited too.
