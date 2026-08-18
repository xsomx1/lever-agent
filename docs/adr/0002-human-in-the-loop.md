# ADR-0002 — Human-in-the-loop on the reject and hire gates

**Status:** accepted · **Date:** 2026-08-18

## Context

The original ask was full funnel automation "from job posting creation to the screening,
interview scheduling and final decision." The API key I hold has the write scopes to do all
of it, including `update an opportunity's stage` and `update an opportunity archived state`
— which is to say, the scopes to reject candidates automatically.

Automated candidate screening is a regulated category:

- The **EU AI Act** classifies employment screening as high-risk.
- **NYC Local Law 144** requires an annual bias audit for automated employment decision
  tools, plus notice to candidates.

The tool being personal narrows the exposure but does not remove it — these are candidates
applying to Xsolla, and the data and the decisions are the company's, not mine.

Existing practice at Xsolla already draws this line. `ai-intern-interview-analyzer` writes
**draft** analyses that a human approves per criterion. The Claude/Lever guide for hiring
managers states plainly that *"Claude is a screening aid and NOT a decision-maker."* And
"no automated email ever reaches a candidate" is a standing guardrail on the AI hiring work.

## Decision

**A human — me — confirms every reject and every hire.** The agent owns everything up to
those gates: screening, ranking, scheduling, drafting feedback, recommending.

Concretely:

- Screening scores are written as **notes**, which are reversible and advisory.
- Stage moves happen **only on explicit confirmation**, one candidate at a time. Never
  batched, never on a schedule.
- Archiving a candidate — the API's reject path — is **not automated at all**.
- **No automated email ever reaches a candidate.**
- Every write has a `--dry-run` that logs the intended call without sending it.

## Consequences

**Good.** Captures most of the throughput win — the expensive part is reading 200 resumes,
not clicking the stage button. Keeps this a productivity tool rather than a compliance
project. Because the key authenticates as me and every write carries `perform_as`, the Lever
audit trail shows a named human, which is exactly what a bias audit would ask for.

**Costs.** The funnel is not fully autonomous, which is a step back from the original ask.
Throughput is bounded by my review time at the decision gates.

**Also worth doing:** a conversation with Legal before the automation boundary widens. Their
answer could change which scopes should stay in use at all — the key already has more than
this decision uses.

**Revisit if:** Legal signs off on a wider boundary, or the volume makes review the actual
bottleneck. Do not revisit by quietly enabling batch stage moves.
