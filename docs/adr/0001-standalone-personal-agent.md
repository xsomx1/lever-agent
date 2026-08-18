# ADR-0001 — A standalone personal CLI, not n8n and not the corporate platform

**Status:** accepted · **Date:** 2026-08-18

## Context

The task began as "an agent for Lever automation via the Lever API and n8n." Two findings
and one clarification moved it somewhere else.

**n8n is being retired at Xsolla.** Founder-level decision by Shurick Agapitov, confirmed by
Moin Moinuddin — no contract renewal, announced in `#ai_general` on 2026-05-19 (PNOPS-2911).
`n8n.xsolla.com` has been locked for editing since 2026-05-12, with all project leaders
demoted to readers (N4J-1213); the contract ends January 2027 and owner migration is due by
2026-12-31. The standing platform rule is *"do NOT add new n8n workflows."* The second
instance, `workflow.xsolla.com`, is on a separate track and still active, but has no
confirmed shutdown date — an open question on XEN-1003 — and runs 2.5.2, which is vulnerable
to CVE-2026-27493 with the upgrade blocked by community-plugin compatibility.

**The corporate target platform is Cloud Run in `xsolla/neuronet-automations`**, where five
Lever jobs already run. That was the initial alternative to n8n.

**But the scope is personal.** This agent is for my own hiring at Xsolla and I am its only
user. That rules out the corporate platform too: `neuronet-automations` is a shared
production repo with a `registry.yaml`, service accounts, and a review path built for
company-wide automations. Putting a single-user tool there means asking other people to
own and review it forever.

## Decision

Build it as a **standalone Python CLI in a private repo under `github.com/xsomx1`**, running
on my own machine.

Not n8n — the platform is going away and the rule says not to add workflows to it.
Not `neuronet-automations` — that is shared infrastructure and this is a personal tool.

## Consequences

**Good.** No platform migration hanging over it. No shared-repo review burden for something
only I use. No dependency on the n8n shutdown timeline. Candidate data stays on my machine.

**Costs.** No visual canvas — and Xsolla has no replacement for one anywhere, which is the
acknowledged gap in the n8n sunset. It only runs when my Mac is awake. If this ever becomes
useful to other hiring managers it has to be rebuilt on the corporate platform; that would be
a rewrite of the runtime, not of the logic, so keeping Lever access and business logic in
separate modules is worth the small effort.

**Boundary to respect.** Internal Xsolla code does not get copied into a personal repo. The
existing `lever-deep-sync/client.py` is a reference implementation to read; the client here
gets written from the public Lever documentation.

**Revisit if:** other hiring managers want it, or Anthropic's Managed Agents (which would host
the loop and the schedule) becomes the easier answer than a launchd job.

## Alternatives rejected

| Option | Why not |
|---|---|
| n8n on `workflow.xsolla.com` | Standing rule against new workflows; no shutdown date; unpatched CVE; credentials can't be exported via API, so migration would be manual |
| n8n on `n8n.xsolla.com` | Locked for editing since 2026-05-12; contract ends Jan 2027 |
| Cloud Run in `neuronet-automations` | Shared production repo and review path; disproportionate for a single-user tool |
| GitHub Actions on a schedule | Would put a write-scoped Lever key in a personal account's secrets and route candidate PII through hosted runners |
