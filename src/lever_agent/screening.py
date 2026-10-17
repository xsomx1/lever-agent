"""Resume screening against a posting's rubric with Claude (T2.2-T2.6).

Resume bytes and their base64 encoding live only in local variables here —
never written to a file, logged, or passed to SnapshotStore (T2.6, ADR-0004).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import BaseModel, ConfigDict

from lever_agent.lever_client import LeverClient
from lever_agent.rubric import Rubric

MODEL = "claude-sonnet-5"  # deliberate cost decision 2026-08-18, see ADR-0003's addendum
SCORE_MAX = 10
DEFAULT_MAX_TOKENS = 8000

# Fixed thresholds on the computed (weighted, 0-10 scale) overall score.
# Deliberately simple and reviewable — not something the model invents.
RECOMMENDATION_BANDS = [
    (8.0, "strong yes"),
    (6.0, "yes"),
    (4.0, "maybe"),
    (0.0, "no"),
]


class ScreeningRefusalError(RuntimeError):
    """Claude returned stop_reason == 'refusal' — do not trust `content`."""


class CriterionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: int  # 0-10; the SDK strips numeric bounds from the schema, so the
    # prompt is what actually constrains this, not a Field(ge=, le=) here
    # (docs/CONTEXT.md §4).
    evidence_quote: str
    rationale: str


class ScreeningVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_verdicts: list[CriterionVerdict]
    summary: str


@dataclass
class CandidateScore:
    opportunity_id: str
    name: str
    overall_score: float
    recommendation: str
    verdict: ScreeningVerdict


def recommendation_band(overall_score: float) -> str:
    for threshold, label in RECOMMENDATION_BANDS:
        if overall_score >= threshold:
            return label
    return RECOMMENDATION_BANDS[-1][1]


def compute_overall_score(rubric: Rubric, verdict: ScreeningVerdict) -> float:
    """Weighted average over the rubric's own weights — computed by us, not the model.

    Keeps the number auditable and reproducible if the rubric changes later.
    """
    scores_by_name = {cv.name: cv.score for cv in verdict.criterion_verdicts}
    total = 0.0
    for criterion in rubric.criteria:
        score = scores_by_name.get(criterion.name)
        if score is None:
            raise ValueError(
                f"verdict is missing a score for rubric criterion '{criterion.name}'"
            )
        total += criterion.weight * score
    return total


def build_system_prompt(rubric: Rubric) -> str:
    criteria_lines = "\n".join(
        f"- {c.name} (weight {c.weight}): {c.description}" for c in rubric.criteria
    )
    return (
        f"You are screening a candidate's resume for the posting "
        f"\"{rubric.posting_title}\".\n\n"
        f"Score the candidate against each of these criteria, on a 0-{SCORE_MAX} "
        f"integer scale (0 = no evidence / poor fit, {SCORE_MAX} = exceptional, "
        f"direct evidence):\n\n{criteria_lines}\n\n"
        "For each criterion, quote the specific evidence from the resume that "
        "supports your score (a short direct quote, not a paraphrase), and give "
        "a one- or two-sentence rationale. Also write a brief overall summary. "
        "Do not compute or state an overall numeric score or hiring "
        "recommendation yourself — that is computed separately from your "
        "per-criterion scores."
    )


async def fetch_resume_bytes(client: LeverClient, opportunity_id: str) -> bytes:
    """The most recent PDF resume's raw bytes for one opportunity (T2.2).

    Live-verified 2026-10-17: a resume record can have `file: None` (a parsed
    profile with no uploaded file); downloading it 400s with "this resume does
    not include a file". Only records with a PDF file are candidates — the model
    call sends the bytes as `application/pdf`.
    """
    resumes = await client.get_resumes(opportunity_id)
    if not resumes:
        raise ValueError(f"opportunity {opportunity_id} has no resume on file")
    with_pdf = [
        r for r in resumes
        if r.get("file") and (r["file"].get("ext") or "").lower() == ".pdf"
    ]
    if not with_pdf:
        exts = sorted({(r.get("file") or {}).get("ext") or "no file" for r in resumes})
        raise ValueError(f"no PDF resume on file (found: {', '.join(exts)})")
    most_recent = max(with_pdf, key=lambda r: r["createdAt"])
    data = await client.download_resume_bytes(opportunity_id, most_recent["id"])
    # Live-verified 2026-10-17: a `.pdf` ext does not guarantee PDF bytes — the API
    # 400s with "The PDF specified was not valid". Check the magic bytes instead.
    if b"%PDF-" not in data[:1024]:
        raise ValueError("resume file has a .pdf extension but is not a valid PDF")
    return data


def score_resume(
    anthropic_client: Anthropic,
    rubric: Rubric,
    resume_pdf_bytes: bytes,
    *,
    model: str = MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[ScreeningVerdict, object]:
    """Score one resume against the rubric. Returns (verdict, raw response for usage/debugging).

    `resume_pdf_bytes` and its base64 form exist only as local variables in
    this call — never persisted (T2.6). `model` defaults to sonnet-5 (a
    deliberate cost decision, see ADR-0003's addendum) but can be overridden
    per call, e.g. to escalate a borderline cohort to opus-5.
    """
    b64 = base64.b64encode(resume_pdf_bytes).decode("ascii")  # no newlines, per docs/CONTEXT.md §4

    system_prompt = build_system_prompt(rubric)
    response = anthropic_client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": "Score this candidate."},
                ],
            }
        ],
        output_format=ScreeningVerdict,
    )

    if response.stop_reason == "refusal":
        raise ScreeningRefusalError(
            "Claude returned stop_reason='refusal' — verdict content is not trustworthy"
        )

    verdict = response.parsed_output
    if verdict is None:
        raise ValueError("no parsed_output on the response despite output_format being set")

    return verdict, response


def rank_candidates(scores: list[CandidateScore]) -> list[CandidateScore]:
    return sorted(scores, key=lambda s: s.overall_score, reverse=True)
