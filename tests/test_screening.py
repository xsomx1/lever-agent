"""Screening logic against a MOCKED OpenAI client — free, deterministic, no real spend.

Live sanity-checking against the real API is scripts/golden_eval.py, run by
hand, not part of this suite.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lever_agent.rubric import Rubric
from lever_agent.screening import (
    RECOMMENDATION_BANDS,
    ScreeningRefusalError,
    ScreeningVerdict,
    build_system_prompt,
    compute_overall_score,
    rank_candidates,
    recommendation_band,
    score_resume,
)
from lever_agent.screening import CandidateScore

RUBRIC = Rubric.model_validate(
    {
        "posting_id": "p1",
        "posting_title": "Test Role",
        "criteria": [
            {"name": "depth", "description": "technical depth", "weight": 0.6},
            {"name": "comms", "description": "communication", "weight": 0.4},
        ],
    }
)


def _verdict(depth_score, comms_score):
    return ScreeningVerdict.model_validate(
        {
            "criterion_verdicts": [
                {"name": "depth", "score": depth_score, "evidence_quote": "x", "rationale": "y"},
                {"name": "comms", "score": comms_score, "evidence_quote": "x", "rationale": "y"},
            ],
            "summary": "ok",
        }
    )


def test_compute_overall_score_is_weighted_average():
    verdict = _verdict(depth_score=10, comms_score=0)
    assert compute_overall_score(RUBRIC, verdict) == pytest.approx(6.0)  # 0.6*10 + 0.4*0


def test_compute_overall_score_missing_criterion_raises():
    verdict = ScreeningVerdict.model_validate(
        {
            "criterion_verdicts": [
                {"name": "depth", "score": 5, "evidence_quote": "x", "rationale": "y"}
            ],
            "summary": "ok",
        }
    )
    with pytest.raises(ValueError, match="missing a score"):
        compute_overall_score(RUBRIC, verdict)


@pytest.mark.parametrize(
    "score,expected",
    [(10, "strong yes"), (8, "strong yes"), (7, "yes"), (5, "maybe"), (2, "no"), (0, "no")],
)
def test_recommendation_band_thresholds(score, expected):
    assert recommendation_band(score) == expected


def test_recommendation_bands_are_sorted_descending():
    thresholds = [t for t, _ in RECOMMENDATION_BANDS]
    assert thresholds == sorted(thresholds, reverse=True)


def test_build_system_prompt_includes_all_criteria_and_weights():
    prompt = build_system_prompt(RUBRIC)
    assert "depth" in prompt
    assert "comms" in prompt
    assert "0.6" in prompt
    assert "0.4" in prompt


def _response(parsed, *, refusal=False):
    part = SimpleNamespace(type="refusal", refusal="no") if refusal else SimpleNamespace(type="output_text")
    return SimpleNamespace(
        status="completed",
        output=[SimpleNamespace(type="reasoning"), SimpleNamespace(type="message", content=[part])],
        output_parsed=parsed,
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def test_score_resume_sends_pdf_file_and_disables_storage():
    fake_client = MagicMock()
    fake_client.responses.parse.return_value = _response(_verdict(8, 6))

    verdict, response = score_resume(fake_client, RUBRIC, b"%PDF-fake")

    assert verdict.summary == "ok"
    call_kwargs = fake_client.responses.parse.call_args.kwargs
    assert call_kwargs["text_format"] is ScreeningVerdict
    assert call_kwargs["store"] is False  # ADR-0004/0006: OpenAI must not retain the response
    file_part = call_kwargs["input"][0]["content"][0]
    assert file_part["type"] == "input_file"
    assert file_part["file_data"].startswith("data:application/pdf;base64,")
    assert "\n" not in file_part["file_data"]  # base64, no newlines


def test_score_resume_raises_on_refusal():
    fake_client = MagicMock()
    fake_client.responses.parse.return_value = _response(None, refusal=True)

    with pytest.raises(ScreeningRefusalError):
        score_resume(fake_client, RUBRIC, b"%PDF-fake")


def test_score_resume_never_opens_a_file(monkeypatch):
    """T2.6: resume bytes must never touch disk."""
    fake_client = MagicMock()
    fake_client.responses.parse.return_value = _response(_verdict(5, 5))

    original_open = open
    calls = []

    def _tracking_open(*args, **kwargs):
        calls.append(args)
        return original_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", _tracking_open)
    score_resume(fake_client, RUBRIC, b"%PDF-fake-resume-bytes")

    assert calls == []


def test_rank_candidates_sorts_descending():
    scores = [
        CandidateScore("a", "A", overall_score=5.0, recommendation="maybe", verdict=_verdict(5, 5)),
        CandidateScore("b", "B", overall_score=9.0, recommendation="strong yes", verdict=_verdict(9, 9)),
        CandidateScore("c", "C", overall_score=1.0, recommendation="no", verdict=_verdict(1, 1)),
    ]
    ranked = rank_candidates(scores)
    assert [s.opportunity_id for s in ranked] == ["b", "a", "c"]
