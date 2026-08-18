"""Load a per-posting screening rubric (T2.1).

Filenames are the Lever posting ID, not a title slug — titles collide across
postings (e.g. the same role opened in two locations), IDs don't.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

RUBRICS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "rubrics"

_WEIGHT_TOLERANCE = 0.01


class RubricCriterion(BaseModel):
    name: str
    description: str
    weight: float


class Rubric(BaseModel):
    posting_id: str
    posting_title: str
    criteria: list[RubricCriterion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "Rubric":
        total = sum(c.weight for c in self.criteria)
        if abs(total - 1.0) > _WEIGHT_TOLERANCE:
            raise ValueError(
                f"rubric criteria weights must sum to 1.0 (±{_WEIGHT_TOLERANCE}); got {total}"
            )
        return self


def rubric_path(posting_id: str, rubrics_dir: Path = RUBRICS_DIR) -> Path:
    return rubrics_dir / f"{posting_id}.yaml"


def load_rubric(posting_id: str, rubrics_dir: Path = RUBRICS_DIR) -> Rubric:
    path = rubric_path(posting_id, rubrics_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"no rubric for posting {posting_id} at {path} — write one before screening it"
        )
    with path.open() as f:
        raw = yaml.safe_load(f)
    return Rubric.model_validate(raw)
