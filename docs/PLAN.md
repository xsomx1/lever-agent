# Lever Hiring Agent — implementation plan

Read [CONTEXT.md](CONTEXT.md) first — it holds the API traps this plan assumes, and the
[ADRs](adr/) hold the four decisions behind it.

## Objective

A personal CLI for my own hiring: pipeline hygiene on the postings I own, plus first-pass
resume screening scored against each posting's rubric. Single user. Human confirms every
reject and every hire.

## Shape

Python CLI in a private repo under `xsomx1`. Lever REST API for data, Claude Opus 5 for
screening, SQLite for local state. Runs on my Mac — on demand for screening, on a schedule
for the digest.

---

# Prerequisites for the build session

Planning was done in its own session; the build starts fresh. Verified state as of 2026-08-18:

| Prerequisite | State | Needed by |
|---|---|---|
| `uv` | ✅ installed (0.12.5, Homebrew) | T0.2 |
| Python 3.13 | ✅ 3.13.15 installed and pinned via `.python-version` | T0.2 |
| Lever API key in Keychain | ✅ stored as `lever-api-key`, verified 2026-08-18: returns real data, `hasNext`/`next` envelope intact. **No confidential-data access** — see below | everything |
| **Anthropic credentials** | ❌ **nothing present** — no `ant` CLI, no `ANTHROPIC_API_KEY`. Simplest path is `brew install anthropics/tap/ant && ant auth login`, which stores an OAuth profile the SDK picks up with no key to manage | **Epic 2** |
| Private repo under `xsomx1` | ❌ not created. `gh` is authed as `xsomx1` | T0.1 |
| `git` | ✅ 2.50.1; this planning repo is on `feature/lever-automation-agent` | T0.1 |

**The only hard blocker left is the one in bold**, and it is not needed until Epic 2 — a
session starting with Epic 1 can begin immediately. The repo is a first-ten-minutes task.

## Verified against the live API, 2026-08-18

Read scope confirmed on every endpoint the plan uses: `postings`, `opportunities`, `stages`,
`archive_reasons`, `disposition_stages`, `webhooks`, `requisitions`, `feedback_templates` —
all 200.

**My Lever user UID: `a245ada8-57eb-4bf7-8354-4635c02627d4`** (Nikita Zinevich). This is the
standing `perform_as` for every write — T0.4 is done.

**The key has no confidential-data access.** `?confidentiality=all` and
`?confidentiality=confidential` both return 403 `NotAuthorized` — *"The key you provided does
not have access to confidential data"*. Plain `GET /v1/opportunities` is 200, and
`?confidentiality=non-confidential` is 200.

This is not fixable on the existing key: in Lever the confidential flag is set **at key
creation and cannot be added later**. Consequences:

- **Never send `confidentiality=all`** — it fails closed with a 403, it does not degrade.
  Leave the parameter off and take the `non-confidential` default.
- Confidential postings and their candidates are **invisible to this agent**. For hiring into
  my own engineering teams that is very likely fine; if a confidential search ever needs to be
  in scope, that requires a **new key** from Van Pham, not a scope change.
- The generic Lever advice "always pass `confidentiality=all` or you will under-count"
  (CONTEXT.md §3) is correct in general and **wrong for this key**. Do not follow it here.

**Start in parallel, because it waits on a person, not on code:** the "AI Screened" question
(T0.7). It blocks Epic 3 and nothing else, so asking now means the answer is there when the
build reaches it.

---

# Epic 0 — Bootstrap

| Task | Description | Done when |
|---|---|---|
| **T0.1** | Create the **private** repo under `xsomx1`, push this planning branch | `gh repo view` shows it private |
| **T0.2** | Toolchain per the prerequisites table above: pin Python 3.13, then `pyproject.toml` with `anthropic`, `httpx`, `tenacity`, `pydantic`, `typer`, `rich` | `uv run lever --help` works |
| **T0.3** | Read the Lever key from the Keychain at runtime (`security find-generic-password -a "$USER" -s lever-api-key -w`) — never from the repo, a `.env`, or an env var baked into a script | Client authenticates with no secret on disk |
| **T0.4** | ✅ **Done 2026-08-18.** Lever user UID is `a245ada8-57eb-4bf7-8354-4635c02627d4` — the standing `perform_as`. Just put it in config | UID in local config |
| **T0.5** | Identify my postings: `GET /v1/postings` with `expand=owner&expand=followers`, filter to me. `state=published` alone omits internal-jobsite postings — also pass `distributionChannel=public&distributionChannel=internal`. **Do not pass `confidentiality`** (see prerequisites) | The posting set matches what I actually hire for |
| **T0.6** | Lever client module: async `httpx`, `asyncio.Semaphore(10)` for the 10 req/s limit, `tenacity` retry with jittered backoff (429 carries no `Retry-After`), cursor pagination on `hasNext`/`next`. Write it fresh from the public docs — do **not** copy the internal `lever-deep-sync` client into a personal repo | Paginates all my postings and their opportunities correctly |
| **T0.7** | Establish what writes to the **"AI Screened"** stage before Epic 3 touches any stage. Likely the `screened.io` marketplace integration — if a vendor owns it, my writes would collide. Check Lever admin → Integrations, or ask Thomas Hansen | Written answer in `CONTEXT.md` §8 |

**Testing:** unit tests for cursor pagination and for the `distributionChannel` default. Add a
guard test asserting the client **never** emits a `confidentiality` parameter — this key 403s on
it, so a stray one fails the request outright rather than degrading. Nothing more.

---

# Epic 1 — Pipeline hygiene and digest

Read-only. Ships first, useful immediately, no risk.

| Task | Description | Done when |
|---|---|---|
| **T1.1** | Per-stage SLA config; flag candidates sitting past it. Watermark on the `updated_at_start` filter, never on the `updatedAt` field | Correct flags across all 13 stages |
| **T1.2** | Posting health: no new applicant in N days, fewer than K active candidates, published longer than a threshold | Flags my stale postings |
| **T1.3** | Terminal digest via `rich` — grouped by posting, sorted by urgency | One command, readable output |
| **T1.4** | Schedule it: `launchd` weekday mornings, output to a file I can open (or a Slack DM to myself if I'd rather) | Fires without me remembering |
| **T1.5** | Store snapshots in SQLite so the digest can show day-over-day movement | Deltas appear on the second run |

**Acceptance:** one week of digests with no false "stale" flags from the `updatedAt` trap.

---

# Epic 2 — Screening and ranking

The core of it. See [ADR-0003](adr/0003-claude-opus-5-native-pdf.md) — the resume PDF goes
straight to Claude as a document block, so there is no text-extraction step at all.

| Task | Description | Done when |
|---|---|---|
| **T2.1** | Rubric per posting: criteria and weights in a small YAML file per posting, versioned in the repo | Rubric for one real posting |
| **T2.2** | Fetch the resume: `GET /v1/opportunities/:id/resumes`, then `.../download` for the file. Base64 it into a `document` content block. Limits: 32 MB request, 100 pages | Resume reaches Claude intact |
| **T2.3** | Score with `claude-opus-5` via `client.messages.parse()` against a Pydantic verdict model — per-criterion score, evidence quote, overall recommendation. Structured outputs guarantee it parses | Schema-valid verdict every time |
| **T2.4** | Cache the rubric and system prompt with `cache_control` (512-token minimum on Opus 5) so screening a cohort pays for the rubric once | `cache_read_input_tokens` non-zero from the second candidate on |
| **T2.5** | Rank a posting's candidates; show the reasoning behind each score, not just the number | I can review a cohort in one screen |
| **T2.6** | Keep resume bytes and extracted text **in memory only** — never to disk, logs, or SQLite. Store the score and reasoning, not the PII | Verified by inspection |

**Cost note:** Opus 5 is $5/M input, $25/M output. Screening is not latency-sensitive, so
if a cohort is large, the Batches API halves it. Worth wiring only if volume justifies it.

**Testing:** a golden set of a few anonymized profiles with expected score bands, so rubric
or prompt edits can't silently drift. This is the one place worth real test investment.

---

# Epic 3 — Writing back to Lever

I have the write scopes and I am the only user, so this is not blocked — but every
irreversible action stays behind my confirmation.

| Task | Description | Done when |
|---|---|---|
| **T3.1** | Post the score to Lever as a note (`POST /v1/opportunities/:id/notes`) with `perform_as` = me. Reversible, low blast radius, immediately useful. Notes created via the API can be edited via the API; notes made in the UI cannot | Score visible on the profile, attributed to me |
| **T3.2** | Tag screened candidates (`addTags`). Careful: tags are free-text, case-sensitive, and auto-created — a typo makes a new tag. Use a fixed constant | Consistent tag, no strays |
| **T3.3** | Stage moves (`PUT /v1/opportunities/:id/stage`) only on explicit confirmation, one candidate at a time, never batched, never scheduled. **Do not write to "AI Screened"** until T0.7 settles who owns it | I advance a candidate from the CLI; Lever reflects it |
| **T3.4** | Local audit log: what changed, when, and the score it was based on. Every write gets a `--dry-run` that logs the intended call without sending it | Dry-run output for every write path |

**Never:** automated rejection, automated hire, or any email to a candidate.

---

# Epic 4 — Interview scheduling (optional)

I hold the scopes, but the API constraint is severe and may make this not worth it.

Interviews can only be created on a panel with `externallyManaged == true`, and **anything a
recruiter booked in the Lever UI cannot be modified via the API at all**. `PUT` on panels and
interviews is a destructive full replace — always GET → merge → PUT.

| Task | Description |
|---|---|
| **T4.1** | Check whether any of my postings actually have externally-managed panels. If not, stop here — the epic is moot |
| **T4.2** | Create a panel + interview from the CLI with `perform_as` = me, `timezone` required (IANA) |
| **T4.3** | Reschedule via the panel endpoint, not per-interview |

---

# Epic 5 — Webhooks (optional)

Only if polling proves too slow. Polling on a schedule matches how I'd use this anyway, and
a webhook needs a public HTTPS endpoint with a CA-signed cert — self-signed is rejected —
which is real infrastructure for a personal tool.

| Task | Description |
|---|---|
| **T5.1** | Receiver for `applicationCreated`, `candidateStageChange` |
| **T5.2** | HMAC-SHA256 verification. The signature is **in the body, not a header**: `hex(hmac_sha256(signing_token, body.token + body.triggeredAt))`. Cache seen tokens against replay. Verification silently no-ops if no signing token was ever generated — assert one exists |
| **T5.3** | Register via `POST /v1/webhooks`, then have a Super Admin toggle the matching group on — the API call alone does not start delivery |

---

# Roadmap

```
Wave 1   Bootstrap        T0.1 … T0.6      ── repo, toolchain, key, Lever client
         ↓
Wave 2   Digest           T1.1 … T1.5      ── read-only; proves the client on real data
         ↓
Wave 3   Screening        T2.1 … T2.6      ── the core value; needs Anthropic access
         ↓
Wave 4   Write-back       T3.1 … T3.4      ── notes first, stage moves last
         ↓
Wave 5   Optional         T4.x  T5.x       ── only if they earn their keep

         T0.7  ────────────────────────────── in parallel from day one; gates Wave 4
```

**Digest before screening**, decided 2026-08-18. The two epics are technically independent, but
this order pays off twice: the digest is read-only and useful within hours, and it exercises the
Lever client — pagination, the `updatedAt` trap, `confidentiality`, rate limiting — against real
data with nothing at risk. Screening then lands on a client that is already known to work,
rather than debugging both layers at once. It also means Wave 1 and Wave 2 need no Anthropic
credential, so the build can start before that access is sorted.

T0.7 (who owns the "AI Screened" stage) sits outside the waves because it waits on a person.
Ask at the start; it only has to be answered before Wave 4.

Full testing at the close of each epic; this document and `CONTEXT.md` get updated as tasks land.

---

# Libraries

| Need | Choice | Why |
|---|---|---|
| Claude | `anthropic` | Native PDF `document` blocks; `messages.parse()` for schema-validated verdicts; prompt caching |
| Verdict schema | `pydantic` | What `messages.parse()` validates against — the schema *is* the model |
| Lever HTTP | `httpx` (async) | Concurrency for the 10 req/s budget |
| Retries | `tenacity` | Lever's 429 has no `Retry-After`; needs backoff with jitter |
| Rate limit | `asyncio.Semaphore(10)` | Stdlib; no library needed |
| CLI | `typer` | Subcommands, help, types from signatures |
| Output | `rich` | The digest is a terminal table; this is what makes it readable |
| State | `sqlite3` (stdlib) | Scores, snapshots, audit log. Local, no server, no PII |

**Deliberately not used:**

- **`pdfplumber`** — obsolete here. Claude accepts PDFs natively, so the whole
  extract-then-prompt step disappears along with its failure modes.
- **`neo4j`** — the corporate jobs write to a graph because they feed a company-wide
  knowledge base. A personal tool has no such need; SQLite is the right size.
- **`aiolimiter`** — a semaphore covers it.

`pydantic` is in the list on purpose, having looked like overhead earlier: with
`messages.parse()` it is the mechanism that guarantees the verdict parses, not a second
validation layer.

---

# Security notes

Worth stating once, because the token is unusually powerful. It carries write access to
production Lever plus the right to download any candidate's resume, and the pipeline holds
6,100 people's personal data under GDPR.

- **Private repo, always.** Never public, even with no data committed.
- **Key in the Keychain**, not `.env`, not GitHub secrets, not a shell profile.
- **No candidate PII on disk** — resumes stay in memory; SQLite holds scores and reasoning.
- **No internal Xsolla code in this repo.** The client gets written from the public Lever
  docs. The internal one is a reference to read, not to copy.
- **`--dry-run` on every write path** before it runs for real. There is no Lever sandbox;
  all testing is against production.
