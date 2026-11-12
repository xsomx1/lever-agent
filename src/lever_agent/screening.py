"""Resume screening against a posting's rubric with OpenAI (T2.2-T2.6, ADR-0006).

Resume bytes and their base64 encoding live only in local variables here —
never written to a file, logged, or passed to SnapshotStore (T2.6, ADR-0004).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from lever_agent.lever_client import LeverClient
from lever_agent.rubric import Rubric

MODEL = "gpt-6.1-terra"  # deliberate cost decision 2026-11-12, see ADR-0006
SCORE_MAX = 10
DEFAULT_MAX_OUTPUT_TOKENS = 8000  # caps reasoning + verdict together

# Fixed thresholds on the computed (weighted, 0-10 scale) overall score.
# Deliberately simple and reviewable — not something the model invents.
RECOMMENDATION_BANDS = [
    (8.0, "strong yes"),
    (6.0, "yes"),
    (4.0, "maybe"),
    (0.0, "no"),
]


class ScreeningRefusalError(RuntimeError):
    """The model returned a refusal instead of a verdict — do not trust the output."""


class CriterionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: int  # 0-10; constrained by the prompt, not a Field(ge=, le=) here —
    # numeric bounds in structured-output schemas are not something to rely on.
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
    openai_client: OpenAI,
    rubric: Rubric,
    resume_pdf_bytes: bytes,
    *,
    model: str = MODEL,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> tuple[ScreeningVerdict, object]:
    """Score one resume against the rubric. Returns (verdict, raw response for usage/debugging).

    `resume_pdf_bytes` and its base64 form exist only as local variables in
    this call — never persisted (T2.6), and `store=False` keeps OpenAI from
    retaining the response either (ADR-0004, ADR-0006). `model` defaults to
    gpt-6.1-terra (a deliberate cost decision, see ADR-0006) but can be
    overridden per call, e.g. to escalate a borderline cohort to gpt-6.1-sol.
    """
    b64 = base64.b64encode(resume_pdf_bytes).decode("ascii")  # no newlines

    response = openai_client.responses.parse(
        model=model,
        max_output_tokens=max_output_tokens,
        instructions=build_system_prompt(rubric),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": "resume.pdf",
                        "file_data": f"data:application/pdf;base64,{b64}",
                    },
                    {"type": "input_text", "text": "Score this candidate."},
                ],
            }
        ],
        text_format=ScreeningVerdict,
        store=False,
    )

    if _has_refusal(response):
        raise ScreeningRefusalError(
            "model returned a refusal — verdict content is not trustworthy"
        )

    verdict = response.output_parsed
    if verdict is None:
        raise ValueError(
            f"no parsed verdict on the response (status={getattr(response, 'status', '?')})"
        )

    return verdict, response


def _has_refusal(response: object) -> bool:
    """A refusal arrives as a `refusal` content item inside a `message` output item."""
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return True
    return False


def rank_candidates(scores: list[CandidateScore]) -> list[CandidateScore]:
    return sorted(scores, key=lambda s: s.overall_score, reverse=True)
