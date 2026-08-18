"""Load config/pipeline.yaml — SLA and posting-health thresholds for the digest.

A small, versioned, hand-tunable file rather than hardcoded constants — same
spirit as the per-posting rubric planned for Epic 2 (T2.1).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "pipeline.yaml"


class PostingHealthConfig(BaseModel):
    max_days_since_last_applicant: float
    min_active_candidates: int
    max_days_published: float


class PipelineConfig(BaseModel):
    stage_sla_days: dict[str, float] = Field(default_factory=dict)
    default_sla_days: float
    no_sla_stages: set[str] = Field(default_factory=set)
    posting_health: PostingHealthConfig

    def sla_for_stage(self, stage_id: str) -> float | None:
        """Days allowed in `stage_id` before it's flagged, or None if exempt."""
        if stage_id in self.no_sla_stages:
            return None
        return self.stage_sla_days.get(stage_id, self.default_sla_days)


def load_pipeline_config(path: Path = DEFAULT_CONFIG_PATH) -> PipelineConfig:
    with path.open() as f:
        raw = yaml.safe_load(f)
    return PipelineConfig.model_validate(raw)
