# ADR-0006 — OpenAI `gpt-6.1-terra` replaces Claude for screening

**Status:** accepted · **Date:** 2026-11-12 · **Supersedes:** [ADR-0003](0003-claude-opus-5-native-pdf.md)

## Context

Screening (Epic 2) scores a resume PDF against a posting's rubric and gets back a
schema-valid verdict. Since 2026-08-18 that ran on Anthropic (`claude-sonnet-5`) through
`messages.parse()` with the PDF as a native `document` block — see ADR-0003.

The decision now is to run screening on OpenAI instead, using an API key from the Xsolla
corporate OpenAI organization. Sending candidate resumes to OpenAI was confirmed as
acceptable on 2026-11-12.

The OpenAI Responses API covers everything ADR-0003 relied on, so the design carries over
unchanged — only the provider call differs:

| ADR-0003 (Anthropic) | This ADR (OpenAI Responses API) |
|---|---|
| `messages.parse(output_format=ScreeningVerdict)` | `responses.parse(text_format=ScreeningVerdict)` → `output_parsed` |
| PDF as a base64 `document` block, 32 MB / 100 pages | PDF as a base64 `input_file` (`data:application/pdf;base64,…`), 50 MB per request |
| `stop_reason == "refusal"` | a `refusal` content item in `response.output` |
| explicit `cache_control` on the system prompt | automatic prefix caching, ≥ 1,024 tokens |

Live-verified 2026-11-12 with `openai` 3.49.0 against a fabricated one-page PDF: the call
returns a schema-valid `ScreeningVerdict`, with `store=False` accepted. The model reasons
by default (57–81 reasoning tokens on that call).

## Decision

**Full replacement, no provider abstraction.** `anthropic` is removed as a dependency. A
switchable provider layer would be code written for a second provider nobody plans to use.

**Model: `gpt-6.1-terra`** ($1 / $5 per 1M tokens) is the default. Escalate a cohort with
`lever screen --model gpt-6.1-sol` or `--model gpt-6-astra` without a code change, the same
mechanism ADR-0003 used.

**Key:** the macOS Keychain, service `openai-api-key`, read the same way as the Lever key.

**`store=False` on every call.** The Responses API stores responses by default. ADR-0004
says no candidate PII is persisted anywhere outside Lever, and that includes OpenAI's
response storage.

**Unchanged from ADR-0003:** native PDF input (no `pdfplumber`), Pydantic structured
output, and the overall score computed by our code from per-criterion scores, not by the
model.

## Consequences

**Good.** One-to-one migration: `score_resume()` keeps its signature, the verdict model and
rubric files don't change, and the code that writes notes and tags to Lever is untouched.
`gpt-6.1-terra` is cheaper per token than Sonnet 5.

**Prompt caching effectively goes away.** The only prefix shared across candidates is the
rubric prompt (~400 tokens), which is below OpenAI's 1,024-token cache minimum. The resume
comes after it and differs per candidate. Measured: `cached_tokens=0` on two identical
calls. At `gpt-6.1-terra` prices this costs well under a cent per candidate, so it isn't
worth padding the prompt to reach the cache threshold.

**Score calibration may shift.** A different model can grade the same evidence differently,
which moves candidates across the strong yes / yes / maybe / no bands.
`scripts/golden_eval.py` plus a dry-run comparison against candidates Sonnet already scored
is the check, before any `--post-notes` run.

**Revisit if:** golden-set or real-candidate scores drift outside their bands on `terra`.
Then escalate the default to `gpt-6.1-sol` before touching the rubric or the prompt.

## Alternatives rejected

| Option | Why not |
|---|---|
| Keep Anthropic behind a provider switch | Extra layer for a fallback no one asked for |
| `gpt-6.1-sol` / `gpt-6-astra` as default | Deliberate cost choice: start on `terra`, escalate per cohort if quality demands |
| Chat Completions API | Responses API is the current path, supports `input_file`, `store`, and `parse()` directly |
