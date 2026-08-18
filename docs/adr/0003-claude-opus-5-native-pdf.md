# ADR-0003 — Claude Opus 5, native PDF input, structured outputs

**Status:** accepted · **Date:** 2026-08-18

## Context

Screening needs three things: get a resume PDF out of Lever, get its content in front of a
model, and get a verdict back in a shape code can act on.

The obvious design — and the one the existing internal `ai-intern-scorer` job uses — is
`pdfplumber` to extract text in memory, then a prompt, then tool-use for a structured
verdict. That job predates what the Claude API now does directly, and copying its shape here
would carry an extraction step that no longer needs to exist.

Two current API capabilities change the design:

**Native PDF input.** A PDF goes into a request as a `document` content block with a base64
source — no beta header. Limits are 32 MB per request and 100 pages on 200k-context models.
The model reads the document itself, including layout and any figures, which a text
extractor discards.

**Structured outputs.** `client.messages.parse()` takes a Pydantic model as
`output_format` and returns a validated instance. Schema conformance is enforced by the API
rather than hoped for, so there is no parse-retry loop and no partially-valid verdict to
defend against.

## Decision

**Model: `claude-opus-5`.** Screening a candidate against a rubric is a judgment task where
a wrong answer wastes an interview slot or loses a good candidate. $5/M input and $25/M
output is the right trade for that.

**Resume delivery: the PDF straight from Lever into a `document` content block.** Download
via `GET /v1/opportunities/:id/resumes/:id/download`, base64 it, send it. No text extraction.

**Verdict: `client.messages.parse()` against a Pydantic model** — per-criterion score, an
evidence quote for each, and an overall recommendation.

**Prompt caching** with `cache_control` on the rubric and system prompt. The minimum
cacheable prefix on Opus 5 is 512 tokens, so a rubric of any substance caches; screening a
cohort then pays for it once instead of per candidate.

Two further notes on Opus 5 that affect the code: thinking is **on by default** (omitting the
`thinking` parameter runs adaptive), and `max_tokens` caps thinking *plus* response text — so
`max_tokens` needs headroom or verdicts truncate. `temperature`, `top_p`, and `budget_tokens`
are rejected outright; behavior gets steered by prompt and by `output_config.effort`.

## Consequences

**Good.** One less dependency and one less failure mode — no extraction step means no
garbled multi-column resumes, no empty output from a scanned PDF, no silent quality loss
before the model ever sees the document. The model reads layout and figures. Verdicts are
schema-guaranteed. Caching makes cohort screening substantially cheaper than per-candidate
pricing suggests.

**Costs.** Sending a PDF costs more input tokens than sending extracted text. Per candidate
this is small and the accuracy is worth it; if a cohort ever gets large enough for it to
matter, the Batches API halves the bill and screening is not latency-sensitive.

The 32 MB / 100-page ceiling is far above any real resume, but the code should fail with a
clear message rather than a 400 if someone attaches a portfolio.

**Revisit if:** input cost becomes the dominant expense at volume, in which case Batches
comes before reintroducing text extraction.

## Alternatives rejected

| Option | Why not |
|---|---|
| `pdfplumber` + text prompt | An extraction step that native PDF input makes unnecessary; loses layout and figures; `pdfplumber` is thinly maintained |
| Tool-use for the verdict | Works, but `messages.parse()` is the purpose-built path and returns a typed object directly |
| `claude-sonnet-5` to save cost | Reasonable for high volume, but this is a judgment call where a wrong answer is expensive. Downgrading is a cost decision to take deliberately, not a default |
