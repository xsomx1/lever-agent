# Context — prior art, constraints, unknowns

Research date: **2026-08-18**. Everything below was verified against live systems or primary
docs. Claims that could not be verified are marked. Re-verify before acting on anything older
than a quarter.

---

## 1. Prior art at Xsolla — reference, not foundation

This agent is a **personal tool in a personal repo** (see [ADR-0001](adr/0001-standalone-personal-agent.md)),
so nothing below is a dependency. It is here for two reasons: to know what has already been
solved and how, and to know what not to collide with. **Internal code does not get copied into
this repo** — read it, learn from it, write fresh from the public docs.

**Worth knowing: every Lever automation at Xsolla today is read-only.** A search of
`xsolla/neuronet-automations` and `xsolla/mini-apps` for `perform_as`, `update_stage`, and any
`POST`/`PUT` to `api.lever.co` returns zero hits. Everything pulls from Lever and writes to
Neo4j, Slack, or GCS. This agent's Epic 3 will be the first write path — which is why it is
worth being careful about what already owns each stage (§8).

Also relevant: **XEN-1350** ("Lever integration: let employees create job postings via
Neuronet", assignee Andrei Smirnov, In Progress as of 2026-08-17) is building a *corporate*
Lever write path with a TA-provisioned key and `perform_as` attribution. Different scope from
this tool — that one is for all employees, this one is for my own hiring — but if a shared
capability ever emerges, that is where it belongs.

### Production jobs (all Cloud Run, project `xsolla-n8n-prod`, region `us-west2`)

Registry of record is `registry.yaml` in `xsolla/neuronet-automations`.

| Job | What it does | Schedule | Owner |
|---|---|---|---|
| `lever-neo4j-sync` | Phase 1. Postings, Stages, Users, Opportunities, Candidates → Neo4j. Bash + curl/jq, 1072 lines | `23 16 * * *` LA, 8h timeout | a.agapitov |
| `lever-deep-sync` | Phase 2. Per-opportunity nested resources (feedback, notes, file metadata, forms, applications, interviews, offers, referrals) → Neo4j. Python async httpx, 8 workers, 10 req/s semaphore, GCS checkpoint | `22 */4 * * *` LA | a.agapitov / a.evseev |
| `lever-deep-sync-backfill` | Same image, `MODE=backfill`. ~400k opportunities × 8 endpoints ≈ 3.2M calls. Manual trigger only | — | same |
| `enrich-talent-lever` | Candidates/postings → `LeverCandidate`/`LeverPosting`, then LLM enrichment | `12 18 * * *` Vladivostok | a.agapitov |
| `expert-hunting-lever-sync` | Scores applicants for 3 hardcoded postings against the expert-hunting rubric. Logic lives in `xsolla/mini-apps apps/expert-hunting/hunter/lever-sync.ts` | `30 6 * * *` UTC | j-manashti |
| `sync-employee-lever-files` | Name-matches `:Employee` ↔ `:LeverCandidate`, writes `HAS_FILE` edges | `40 18 * * *` Vladivostok | j-chark |
| `aggregate-talent-profiles` | Merges Slack + HiBob + Lever into `TalentProfile` | `18 16 * * 0` | a.agapitov |

> `enrich-talent-lever`: the checked-in `main.py` is a documented **placeholder** (140 lines).
> Real logic exists only in the deployed container image. Its documented behaviour is unverified.

### The AI-First Intern pipeline — the most mature AI hiring automation here

This is the template to generalize, not to rebuild.

| Job | What it does |
|---|---|
| `ai-intern-scorer` | Reads application answers + resume PDFs live from Lever → `pdfplumber` in-memory extraction → Claude `claude-sonnet-5` tool-use rubric scoring → writes `CandidateScreeningScore` to Neo4j. Covers 9 `ai-first-intern` postings + 1 `solutions-engineer-enterprise`. **No PII persisted.** `37 */4 * * *` LA |
| `ai-intern-interview-analyzer` | Reads interview feedback already in Neo4j (no Lever calls) → Claude → writes **draft** `CandidateInterviewAIAnalysis`. Never a submitted scorecard; a human approves each criterion |
| `ai-intern-pipeline-report` | Live Lever pull → Slack report to `C0BFVD59K51`, weekdays 15:00 PT, day-over-day deltas via GCS snapshot |
| `ai-repo-inspector-scorer` | Grades take-home submissions from GitHub advisories → `:AssessmentAssignment`. Matches email→opportunity via Neo4j Cypher, **not** the Lever API |
| `ai-intern-screening` mini-app | Human review surface, https://prototype.xsolla.dev/mini-apps/ai-intern-screening — reads Neo4j, no writes |

### Reusable code — read this before writing anything

**`jobs/lever-deep-sync/client.py`** (211 lines) is a production-grade async Lever client:

- `LEVER_API_BASE = "https://api.lever.co/v1"`, `DEFAULT_PAGE_SIZE = 100`
- `DEFAULT_GLOBAL_CONCURRENCY = 10` — an `asyncio.Semaphore` honouring Lever's 10 req/s
- `list_paginated()` implements the `hasNext` / `next` cursor correctly
- `fetch_opportunity_endpoint()` for nested resources
- Retry via `tenacity`, `_Retryable` / `LeverNonRetriableError` split
- Read-only — no write methods

Dependency baselines already in use:

```
# lever-deep-sync
neo4j>=6.2.0,<7.0.0   httpx>=0.27,<0.30
google-cloud-storage>=2.14.0,<3.0.0   tenacity>=8.2.0,<10.0.0

# ai-intern-scorer
anthropic>=0.40,<1.0   neo4j>=6.2.0,<7.0.0   pdfplumber>=0.11,<1.0   requests>=2.31,<3.0
```

### Credentials

GCP Secret Manager, project `xsolla-n8n-prod`:

| Secret | Used by |
|---|---|
| `neuronet_lever_api_key` | lever-neo4j-sync, lever-deep-sync(+backfill), enrich-talent-lever, expert-hunting-lever-sync, ai-intern-pipeline-report |
| `neuronet_user_j_manashti_lever_api_key` | ai-intern-scorer |

The repo has an established **per-user secret convention** (`neuronet_user_<user>_<system>_key`).
It exists because of a real incident: a shared token silently returned HTTP 200 with empty
results and had to be replaced with a personal one. Rate limits are **per API key**, so a key
shared between a sync job and a reactive service will contend — split keys per workload.

Not determined: who administratively owns/rotates `neuronet_lever_api_key`, and which Lever
user/role the keys map to.

---

## 2. The live pipeline

Pulled from the Lever API on 2026-08-18: **6,100 candidates, 185 published postings, 13 stages.**
The Confluence guide (DHGP 23574806687, owner Sabrina Morgan) is **stale by two stages**.

| # | Stage | ID | Documented? |
|---|---|---|---|
| 1 | New lead | `lead-new` | yes |
| 2 | Reached out | `lead-reached-out` | yes |
| 3 | Responded | `lead-responded` | yes |
| 4 | New applicant | `applicant-new` | yes |
| 5 | **AI Screened** | `011016a8-16d0-44f4-b95e-1af10019606f` | **no** |
| 6 | Recruiter Scheduling Interview | `428c0bf5-a68a-4b3b-a5e9-be699458ef13` | yes |
| 7 | On Hold | `bb38c734-716b-46a9-bc24-7d72b66e73da` | yes |
| 8 | **HR manager screen** | `a48ce2e9-6df3-4438-a687-49a0ea05923f` | **no** |
| 9 | Interview | `f97cd673-55a2-4f73-91f8-b06117e0b65b` | yes |
| 10 | Test task | `b78629d6-a3a8-4177-9ab9-866968547729` | yes |
| 11 | Final Interview | `14c4fdf5-4d99-41be-9b4b-2b529d37cf7b` | yes |
| 12 | Reference check | `8450b77c-f977-4f02-97f1-2452aaa65d7e` | yes |
| 13 | Offer | `offer` | yes |

"Hired" is **not** a stage — it is *archived with archive reason = Hired*.

---

## 3. Lever API — constraints that shape the design

Source: https://hire.lever.co/developer/documentation

**Auth.** `https://api.lever.co/v1`, HTTP Basic with the API key as username and a blank
password: `curl -u API_KEY: https://api.lever.co/v1/opportunities`. Confidential-data access is
a **key-creation-time flag and cannot be added later**. OAuth exists but is for partner
integrations, not internal automation. There is **one global host** — `api.eu.lever.co/v1`
301-redirects to `api.lever.co/v1`.

**Rate limits.** Token bucket, **per API key**: 10 req/s steady, bursts to 20 req/s. Over-limit
returns **429 with no `Retry-After` and no `X-RateLimit-*` headers** — use blind exponential
backoff with jitter. Also back off on 503.

**Pagination.** Opaque cursor despite the param being named `offset`. Response carries
`data`, `next`, `hasNext`. Pass the `next` token back verbatim — never synthesize it. `limit`
1–100, default 100 (50 on `GET /applications/deleted`).

**Timestamps** are integer **epoch milliseconds**, UTC. All `*_at_start` / `*_at_end` filters too.

**Traps that will silently corrupt results:**

1. **`updated_at_start` does not correspond to the `updatedAt` field** — documented explicitly.
   The filter matches any change; the field only bumps for an enumerated subset, and can be
   `null`. **Watermark incremental sync on the filter, never on the returned field.**
2. **Confidentiality defaults to exclusion.** `/opportunities`, `/postings`, `/requisitions`
   default to `confidentiality=non-confidential`. In general you pass `confidentiality=all` or
   under-count silently — **but not with our key.** Verified 2026-08-18: our key has no
   confidential-data access, so `confidentiality=all` returns 403 `NotAuthorized` rather than
   degrading. Leave the parameter off entirely; confidential postings are out of scope. The
   flag is set at key creation and cannot be added later — widening scope means a new key.
   See PLAN.md → Verified against the live API.
3. **`state=published` alone omits internal-jobsite postings.** Also pass
   `distributionChannel=public&distributionChannel=internal`.
4. **Tags and sources are free-text, case-sensitive, and auto-created on write.** A typo makes
   a new tag. `GET /sources` returns `{text, count}` — no IDs.
5. **Query params are `snake_case`, JSON bodies and response fields are `camelCase`**, with
   exceptions in both directions. Do not auto-convert case.
6. **`GET /stages` returns only `{id, text}`** — no ordering. Use `GET /disposition_stages` for
   pipeline order plus archive reasons in one call.
7. Repeatable filters (`tag`, `origin`, `stage_id`, `posting_id`, …) are **OR**, not AND.

**Contact vs Opportunity.** `Contact` = the person (stable identity). `Opportunity` = one
candidacy. One Contact → many Opportunities; one Opportunity → **at most one** Application. The
legacy `candidateId` equals the `opportunityId`, so IDs migrate cleanly but the semantics
changed. There is **no person-level list endpoint** — "all notes for a candidate" needs
`GET /opportunities?contact_id=…` then a per-opportunity fan-out.

**Writes.** `perform_as` is a **query-string** param taking a Lever user UID. It sets both
attribution and the effective permission set.

- **Required** for: `POST /opportunities`, all interview/panel/feedback create-update-delete,
  file upload and delete.
- **Optional** for: `PUT /opportunities/:id/stage`, `PUT /opportunities/:id/archived`,
  add/remove links-tags-sources, `POST /opportunities/:id/notes`, `POST|PUT /postings`.
- 403 means the `perform_as` user lacks the in-app permission.

**Scheduling is heavily constrained.** Interviews can only be created on an existing panel, and
**only where `externallyManaged == true`**. Anything a recruiter booked in the Lever UI cannot
be modified or rescheduled via the API. `PUT` on interviews, panels, and notes is a **destructive
full replace** — "missing fields will be deleted". Always GET → merge → PUT.

**API-created and UI-created objects are partitioned.** Notes, interviews, panels, and webhooks
made in the UI are invisible to API updates, and vice versa. Pick one management path.

**Webhooks.** 10 event types: `applicationCreated`, `candidateHired`, `candidateStageChange`,
`candidateArchiveChange`, `candidateDeleted`, `interviewCreated|Updated|Deleted` (beta),
`contactCreated`, `contactUpdated`.

- The HMAC-SHA256 **signature is in the body, not a header**. Verify as
  `hex(hmac_sha256(signing_token, body.token + body.triggeredAt))` — token first.
- **A signature is only present if a signing token was generated** — verification silently
  no-ops otherwise. Cache seen `token` values against replay; reject stale `triggeredAt`.
- HTTPS only, cert must chain to a public CA — **self-signed is rejected**.
- Respond 2xx. Anything else, **including 3xx**, counts as failure. 5 retries with backoff.
- **No published IP allowlist.** Do not build a firewall assumption; rely on the HMAC.
- After `POST /webhooks` succeeds a **Super Admin must still toggle the matching webhook group
  on** in account settings before data flows.

**GDPR.** There is no delete-my-data endpoint. Read-only surfaces: `dataProtection.store`,
`dataProtection.contact`, `isAnonymized`. For deletion propagation poll
`GET /opportunities/deleted`, `/postings/deleted`, `/applications/deleted` (required window,
**max 30 days**) and subscribe to `candidateDeleted`.

**No sandbox.** `api.sandbox.lever.co` exists but accounts are issued only to approved
integration partners. No reference to an Xsolla sandbox was found anywhere. **Assume all work
runs against production Lever.**

---
## 4. OpenAI API — what the screening design relies on

Verified against the live API with `openai` 3.49.0, 2026-11-12. Replaces the Claude API
notes that stood here until then (see [ADR-0006](adr/0006-openai-gpt-6-1-terra.md); the old
design is in [ADR-0003](adr/0003-claude-opus-5-native-pdf.md)).

**Native PDF input** via the Responses API, as an `input_file` part placed before the text:

```json
{"type": "input_file", "filename": "resume.pdf", "file_data": "data:application/pdf;base64,<b64>"}
```

Limit: **50 MB per request** (all files combined). For vision-capable models the API sends
both the extracted text and page images, so there is still no text-extraction step here and
no `pdfplumber`.

**Structured outputs.** `client.responses.parse(text_format=ScreeningVerdict)` returns a
validated instance in `response.output_parsed`. A refusal arrives as a `refusal` content
item inside a `message` output item, not as a parsed verdict — check for it first.
`output_parsed` is `None` when the response is `incomplete` (e.g. `max_output_tokens` hit).

**Model: `gpt-6.1-terra`** ($1 / $5 per MTok), escalation via `--model gpt-6.1-sol` ($2 / $10)
or `gpt-6-astra` ($10 / $50). Reasons by default; `max_output_tokens` caps reasoning plus
the verdict, so it needs headroom.

**`store=False` on every call.** The Responses API stores responses unless told not to;
ADR-0004 rules that out for candidate data.

**Prompt caching is automatic but does not kick in here.** The minimum cacheable prefix is
1,024 tokens; the only prefix shared across candidates is the rubric prompt (~400 tokens).
Measured: `usage.input_tokens_details.cached_tokens` stays 0. Not worth padding for at
`terra` prices.

**Batch API** halves the cost if a cohort ever gets large; screening is not
latency-sensitive.

---

## 5. n8n — why it is not the platform

Recorded because the task started there. Full reasoning in
[ADR-0001](adr/0001-standalone-personal-agent.md).

- **n8n is being retired at Xsolla** — founder-level decision (Shurick Agapitov), confirmed by
  Moin Moinuddin, announced in `#ai_general` 2026-05-19 (PNOPS-2911).
- `n8n.xsolla.com` (Enterprise, Okta) has been **locked for editing since 2026-05-12**;
  contract ends **January 2027**, owner migration due **2026-12-31** (N4J-1213).
- Standing rule: **"do NOT add new n8n workflows."**
- `workflow.xsolla.com` (Community, 2.5.2) is on a separate track and still active, but has
  **no confirmed shutdown date** (open on XEN-1003) and is vulnerable to **CVE-2026-27493**
  with the upgrade blocked by community-plugin compatibility. Form Trigger paths are
  corporate-IP allowlisted and `/form-waiting` is hard-blocked; ordinary `/webhook/` paths work.
- Owner of both instances and the `xsolla-n8n-prod` GCP project: **Anton Evseev**
  (a.evseev@xsolla.com).

Also recorded: n8n has **no native Lever node** (verified against the full 33,479-path repo
tree and the 1,364-entry docs sitemap; the integrations page 404s). The only community node
is a single 2026-04-25 release with 3 weekly downloads, unverified, and unusable on Cloud.

---

## 6. Regulatory boundary

Automated candidate screening is regulated: the **EU AI Act** classifies employment screening
as high-risk, and **NYC Local Law 144** requires an annual bias audit for automated employment
decision tools plus candidate notice.

Decision and its consequences: [ADR-0002](adr/0002-human-in-the-loop.md). In short — a human
confirms every reject and every hire; the agent owns everything up to those gates; no
automated email ever reaches a candidate.

Worth a conversation with Legal before the boundary widens, since the API key already carries
more write scope than this decision uses.

---

## 7. People

Nobody's sign-off is needed to build this — it is a personal tool. These are the people whose
answers matter when a question comes up.

- **Van Pham** (U08J5BNE003) — Lever admin, issues API tokens. The route if the key needs
  changing or a scope is missing.
- **Thomas Hansen** (t.hansen@xsolla.com) — Technical Recruiter, wrote the Claude/Lever
  integration guide for hiring managers. The person to ask what owns the "AI Screened" stage.
- **Sabrina Morgan** (s.morgan@xsolla.com) — process owner for the Lever pipeline definition.
  The DHGP pipeline guide is hers, and it is stale by two stages (§2).
- **Javad Manashti** (j.manashti@xsolla.com) — built the AI-First Intern screening pipeline.
  Closest prior art to Epic 2; worth comparing notes with rather than duplicating.
- **Katarina Hunt** (k.hunt@xsolla.com) — runs the TA Recruitment Weekly Sync, owns the
  intern pipeline Slack report. Knows what the TA org already gets automatically.
- **Andrei Smirnov** (an.smirnov@xsolla.com) — XEN-1350, the corporate Lever write path.
  Relevant only if this ever needs to become a shared capability.

**Channels:** `#tech-ta-hire-chat`, `#current-direct-lever-build`,
`#team-offer-process-and-support`. Lever access requests go through HR Service Desk portal
**1018**.

---

## 8. Open unknowns

1. ~~**What writes to the "AI Screened" stage**~~ — **Answered 2026-08-18 by Thomas Hansen**
   (Slack DM, asked 2026-08-18): **no vendor/marketplace integration owns this stage.** The
   `screened.io` hypothesis (a Lever marketplace product documented in AI1 page 23732617239
   as syncing postings/resumes out of Lever and writing evaluations back) is **ruled out** —
   Thomas confirmed it isn't connected. The stage is used **manually** by some HR staff and
   hiring managers; Thomas himself doesn't use it. Consequence: the collision risk this task
   existed to check was a system/integration one, and there is none — so the hard block on
   "AI Screened" as a stage-move target in `writes.py::advance_stage` was lifted 2026-08-18.
   It's now an ordinary stage move like any other, subject to the same one-at-a-time,
   explicit-confirmation, `--dry-run`-available discipline as every other target.
2. **No Lever sandbox.** `api.sandbox.lever.co` exists but accounts go only to approved
   integration partners, and no reference to an Xsolla sandbox was found anywhere. **All
   testing runs against production** — hence `--dry-run` on every write path.
3. **Whether any of my postings have externally-managed interview panels.** Decides whether
   Epic 4 is possible at all; the API cannot touch panels booked in the Lever UI.
4. **`state=published` scope.** Confirm my posting set isn't missing internal-jobsite
   postings (`distributionChannel`) or confidential ones (`confidentiality=all`) — both
   default to exclusion (§3).

Deliberately dropped as no longer relevant: the Ashby ATS evaluation (a personal tool is
cheap to abandon), and the corporate deployment questions from the earlier framing.

**One caution about internal docs:** the "AI Hiring Platform" pages in the AI1 Confluence
space read as a shipped system with metrics — 18-day time-to-hire, $720K/yr savings, 2,800%
ROI — but the named repo `xsolla/ai-hiring-platform` **does not exist**, the endpoints appear
nowhere in `registry.yaml`, and the one genuine artifact (HJB-153, a real auto-created JD
approval subtask from 2026-01-16) is **Discontinued**. Design intent, not a system.
