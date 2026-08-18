"""Rubric loading and the weights-sum-to-1.0 guard (T2.1)."""

import pytest
from pydantic import ValidationError

from lever_agent.rubric import Rubric, load_rubric, rubric_path

REAL_POSTING_ID = "f5349e52-94b9-4eb7-aaea-e83b001854a3"


def test_loads_the_real_iam_rubric():
    rubric = load_rubric(REAL_POSTING_ID)
    assert rubric.posting_id == REAL_POSTING_ID
    assert len(rubric.criteria) > 0
    total_weight = sum(c.weight for c in rubric.criteria)
    assert total_weight == pytest.approx(1.0, abs=0.01)


def test_missing_rubric_raises_clear_error():
    with pytest.raises(FileNotFoundError, match="no rubric for posting"):
        load_rubric("does-not-exist")


def test_weights_must_sum_to_one():
    with pytest.raises(ValidationError, match="sum to 1.0"):
        Rubric.model_validate(
            {
                "posting_id": "p1",
                "posting_title": "Test",
                "criteria": [
                    {"name": "a", "description": "x", "weight": 0.5},
                    {"name": "b", "description": "y", "weight": 0.2},
                ],
            }
        )


def test_rubric_path_uses_posting_id_not_title():
    path = rubric_path("abc-123")
    assert path.name == "abc-123.yaml"
