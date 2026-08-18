"""SLA flags, posting health, and urgency sort order — all pure, deterministic."""

from lever_agent.digest import build_digest, compute_posting_health, compute_stage_flags
from lever_agent.pipeline_config import PipelineConfig

NOW_MS = 1_800_000_000_000  # arbitrary fixed "now" so tests never depend on the real clock
DAY = 86_400_000

CONFIG = PipelineConfig.model_validate(
    {
        "stage_sla_days": {"applicant-new": 3, "interview": 7},
        "default_sla_days": 5,
        "no_sla_stages": ["on-hold"],
        "posting_health": {
            "max_days_since_last_applicant": 14,
            "min_active_candidates": 5,
            "max_days_published": 60,
        },
    }
)


def _opportunity(id_, stage, days_ago, archived=False):
    return {
        "id": id_,
        "name": f"Candidate {id_}",
        "stage": stage,
        "lastAdvancedAt": NOW_MS - int(days_ago * DAY),
        "createdAt": NOW_MS - int(days_ago * DAY),
        "archived": {"reason": "x"} if archived else None,
    }


def test_flags_candidate_past_stage_sla():
    opportunities = [_opportunity("a", "applicant-new", days_ago=4)]
    flags = compute_stage_flags(opportunities, CONFIG, NOW_MS)
    assert len(flags) == 1
    assert flags[0].opportunity_id == "a"
    assert flags[0].days_over > 0


def test_does_not_flag_candidate_within_sla():
    opportunities = [_opportunity("a", "applicant-new", days_ago=1)]
    assert compute_stage_flags(opportunities, CONFIG, NOW_MS) == []


def test_default_sla_applies_to_unlisted_stage():
    opportunities = [_opportunity("a", "some-other-stage", days_ago=6)]
    flags = compute_stage_flags(opportunities, CONFIG, NOW_MS)
    assert len(flags) == 1  # default_sla_days=5, 6 > 5


def test_on_hold_stage_is_never_flagged():
    opportunities = [_opportunity("a", "on-hold", days_ago=365)]
    assert compute_stage_flags(opportunities, CONFIG, NOW_MS) == []


def test_archived_opportunities_are_never_flagged():
    opportunities = [_opportunity("a", "applicant-new", days_ago=100, archived=True)]
    assert compute_stage_flags(opportunities, CONFIG, NOW_MS) == []


def test_posting_health_flags_all_three_conditions():
    posting = {"id": "p1", "text": "Some Role", "state": "published", "createdAt": NOW_MS - 90 * DAY}
    opportunities = [_opportunity("a", "applicant-new", days_ago=20)]  # only 1 active, applied 20d ago

    health = compute_posting_health(posting, opportunities, CONFIG, NOW_MS)

    assert health.below_min_active is True  # 1 < 5
    assert health.no_recent_applicant is True  # 20 > 14
    assert health.stale_publication is True  # 90 > 60


def test_posting_health_clean_posting_has_no_flags():
    posting = {"id": "p1", "text": "Some Role", "state": "published", "createdAt": NOW_MS - 10 * DAY}
    opportunities = [_opportunity(str(i), "applicant-new", days_ago=1) for i in range(6)]

    health = compute_posting_health(posting, opportunities, CONFIG, NOW_MS)

    assert health.has_flags is False


def test_build_digest_sorts_flagged_postings_first_then_by_worst_overdue():
    healthy_posting = {"id": "healthy", "text": "Healthy", "state": "published", "createdAt": NOW_MS - 5 * DAY}
    healthy_opps = [_opportunity(str(i), "applicant-new", days_ago=1) for i in range(6)]

    mildly_late_posting = {"id": "mild", "text": "Mildly late", "state": "published", "createdAt": NOW_MS - 5 * DAY}
    mildly_late_opps = [_opportunity(str(i), "applicant-new", days_ago=4) for i in range(6)]

    very_late_posting = {"id": "very", "text": "Very late", "state": "published", "createdAt": NOW_MS - 5 * DAY}
    very_late_opps = [_opportunity(str(i), "applicant-new", days_ago=20) for i in range(6)]

    digests = build_digest(
        [
            (healthy_posting, healthy_opps),
            (mildly_late_posting, mildly_late_opps),
            (very_late_posting, very_late_opps),
        ],
        CONFIG,
        NOW_MS,
    )

    assert [d.health.posting_id for d in digests] == ["very", "mild", "healthy"]
