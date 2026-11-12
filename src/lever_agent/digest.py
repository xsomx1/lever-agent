"""Pure domain logic for the pipeline-hygiene digest (T1.1, T1.2, T1.3's sort order).

Deliberately takes `now_ms` as a parameter everywhere instead of calling
`time.time()` internally — keeps this module a pure function of its inputs,
so it's fully unit-testable without mocking the clock or the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lever_agent.pipeline_config import PipelineConfig

MS_PER_DAY = 86_400_000


@dataclass
class CandidateFlag:
    opportunity_id: str
    name: str
    stage_id: str
    days_in_stage: float
    sla_days: float

    @property
    def days_over(self) -> float:
        return self.days_in_stage - self.sla_days


@dataclass
class PostingHealth:
    posting_id: str
    posting_title: str
    active_count: int
    days_since_last_applicant: float | None  # None if no applicants at all
    days_published: float
    no_recent_applicant: bool = False
    below_min_active: bool = False
    stale_publication: bool = False

    @property
    def has_flags(self) -> bool:
        return self.no_recent_applicant or self.below_min_active or self.stale_publication


@dataclass
class PostingDigest:
    health: PostingHealth
    candidate_flags: list[CandidateFlag] = field(default_factory=list)

    @property
    def urgency(self) -> tuple[int, float]:
        """Sort key: health-flagged postings first, then by worst overdue candidate."""
        worst_overdue = max((f.days_over for f in self.candidate_flags), default=0.0)
        return (0 if self.health.has_flags else 1, -worst_overdue)


def compute_stage_flags(
    opportunities: list[dict[str, Any]],
    config: PipelineConfig,
    now_ms: int,
) -> list[CandidateFlag]:
    """Flag active opportunities that have sat past their stage's SLA.

    Uses `lastAdvancedAt`, not `updatedAt` — verified 2026-08-18 that only the
    former reliably marks the last stage change (docs/CONTEXT.md §3.1).
    """
    flags: list[CandidateFlag] = []
    for opp in opportunities:
        if opp.get("archived"):
            continue
        stage_id = opp.get("stage")
        sla_days = config.sla_for_stage(stage_id)
        if sla_days is None:
            continue
        last_advanced_at = opp.get("lastAdvancedAt")
        if last_advanced_at is None:
            continue
        days_in_stage = (now_ms - last_advanced_at) / MS_PER_DAY
        if days_in_stage > sla_days:
            flags.append(
                CandidateFlag(
                    opportunity_id=opp["id"],
                    name=opp.get("name", "?"),
                    stage_id=stage_id,
                    days_in_stage=days_in_stage,
                    sla_days=sla_days,
                )
            )
    return flags


def compute_posting_health(
    posting: dict[str, Any],
    opportunities: list[dict[str, Any]],
    config: PipelineConfig,
    now_ms: int,
) -> PostingHealth:
    active = [opp for opp in opportunities if not opp.get("archived")]
    active_count = len(active)

    applicant_created_ats = [opp["createdAt"] for opp in active if opp.get("createdAt") is not None]
    days_since_last_applicant = (
        (now_ms - max(applicant_created_ats)) / MS_PER_DAY if applicant_created_ats else None
    )

    days_published = (now_ms - posting["createdAt"]) / MS_PER_DAY

    health_config = config.posting_health
    no_recent_applicant = (
        days_since_last_applicant is not None
        and days_since_last_applicant > health_config.max_days_since_last_applicant
    )
    below_min_active = active_count < health_config.min_active_candidates
    stale_publication = (
        posting.get("state") == "published"
        and days_published > health_config.max_days_published
    )

    return PostingHealth(
        posting_id=posting["id"],
        posting_title=posting.get("text", "?"),
        active_count=active_count,
        days_since_last_applicant=days_since_last_applicant,
        days_published=days_published,
        no_recent_applicant=no_recent_applicant,
        below_min_active=below_min_active,
        stale_publication=stale_publication,
    )


def build_digest(postings_with_opportunities: list[tuple[dict[str, Any], list[dict[str, Any]]]],
                  config: PipelineConfig, now_ms: int) -> list[PostingDigest]:
    """Build one PostingDigest per posting, sorted worst-first."""
    digests = []
    for posting, opportunities in postings_with_opportunities:
        health = compute_posting_health(posting, opportunities, config, now_ms)
        flags = compute_stage_flags(opportunities, config, now_ms)
        flags.sort(key=lambda f: f.days_over, reverse=True)
        digests.append(PostingDigest(health=health, candidate_flags=flags))
    digests.sort(key=lambda d: d.urgency)
    return digests
