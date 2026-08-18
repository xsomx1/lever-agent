"""Write paths to Lever (T3.1-T3.3) — every one dry-run-capable and audit-logged.

Per ADR-0002 (human-in-the-loop): notes and tags are additive/reversible and
write directly when called; stage moves are one-candidate-at-a-time and need
explicit interactive confirmation in the real (non-dry-run) path. Nothing here
can archive, reject, hire, or email a candidate — those paths don't exist in
this module, by design.
"""

from __future__ import annotations

from dataclasses import dataclass

from lever_agent.audit_log import AuditLog, AuditLogEntry
from lever_agent.config import AI_SCREENED_STAGE_ID, SCREENING_TAG
from lever_agent.lever_client import LeverClient
from lever_agent.rubric import Rubric
from lever_agent.screening import CandidateScore


class AIScreenedStageBlockedError(RuntimeError):
    """Refused: T0.7 (who else writes to "AI Screened") is still unanswered."""


@dataclass
class WriteResult:
    action: str  # 'note' | 'tag' | 'stage_move'
    opportunity_id: str
    detail: str
    dry_run: bool
    would_send: dict | None = None  # request body/params, for dry-run previews


def build_note_text(rubric: Rubric, score: CandidateScore) -> str:
    """Compact note body — the full per-criterion transcript stays local (`--detail`)."""
    lines = [f"[lever-agent] score {score.overall_score:.1f}/10 ({score.recommendation})"]
    for cv in score.verdict.criterion_verdicts:
        lines.append(f"- {cv.name}: {cv.score}/10")
    lines.append(f"Summary: {score.verdict.summary}")
    return "\n".join(lines)


async def write_note(
    client: LeverClient,
    audit: AuditLog,
    posting_id: str,
    score: CandidateScore,
    note_text: str,
    *,
    now_ms: int,
    dry_run: bool = False,
) -> WriteResult:
    success = True
    if not dry_run:
        try:
            await client.create_note(score.opportunity_id, note_text)
        except Exception:
            audit.record(
                AuditLogEntry(
                    timestamp_ms=now_ms,
                    opportunity_id=score.opportunity_id,
                    posting_id=posting_id,
                    action="note",
                    detail=f"score={score.overall_score:.1f}",
                    dry_run=False,
                    success=False,
                )
            )
            raise
    audit.record(
        AuditLogEntry(
            timestamp_ms=now_ms,
            opportunity_id=score.opportunity_id,
            posting_id=posting_id,
            action="note",
            detail=f"score={score.overall_score:.1f}",
            dry_run=dry_run,
            success=success,
        )
    )
    return WriteResult(
        action="note",
        opportunity_id=score.opportunity_id,
        detail=note_text,
        dry_run=dry_run,
        would_send={"value": note_text} if dry_run else None,
    )


async def write_tag(
    client: LeverClient,
    audit: AuditLog,
    posting_id: str,
    opportunity_id: str,
    *,
    now_ms: int,
    tag: str = SCREENING_TAG,
    dry_run: bool = False,
) -> WriteResult:
    success = True
    if not dry_run:
        try:
            await client.add_tags(opportunity_id, [tag])
        except Exception:
            audit.record(
                AuditLogEntry(
                    timestamp_ms=now_ms,
                    opportunity_id=opportunity_id,
                    posting_id=posting_id,
                    action="tag",
                    detail=tag,
                    dry_run=False,
                    success=False,
                )
            )
            raise
    audit.record(
        AuditLogEntry(
            timestamp_ms=now_ms,
            opportunity_id=opportunity_id,
            posting_id=posting_id,
            action="tag",
            detail=tag,
            dry_run=dry_run,
            success=success,
        )
    )
    return WriteResult(
        action="tag",
        opportunity_id=opportunity_id,
        detail=tag,
        dry_run=dry_run,
        would_send={"tags": [tag]} if dry_run else None,
    )


async def advance_stage(
    client: LeverClient,
    audit: AuditLog,
    posting_id: str,
    opportunity_id: str,
    target_stage_id: str,
    target_stage_name: str,
    *,
    now_ms: int,
    dry_run: bool = False,
) -> WriteResult:
    """T3.3. Callers (the CLI) are responsible for the interactive confirmation
    prompt in the real (non-dry-run) path — this function only enforces the
    hard AI-Screened block, unconditionally, before any network call.
    """
    if target_stage_id == AI_SCREENED_STAGE_ID:
        raise AIScreenedStageBlockedError(
            "Refusing to move a candidate into the 'AI Screened' stage — "
            "T0.7 (who else writes to it) is still unanswered. See docs/PLAN.md T0.7."
        )

    success = True
    if not dry_run:
        try:
            await client.update_stage(opportunity_id, target_stage_id)
        except Exception:
            audit.record(
                AuditLogEntry(
                    timestamp_ms=now_ms,
                    opportunity_id=opportunity_id,
                    posting_id=posting_id,
                    action="stage_move",
                    detail=target_stage_name,
                    dry_run=False,
                    success=False,
                )
            )
            raise
    audit.record(
        AuditLogEntry(
            timestamp_ms=now_ms,
            opportunity_id=opportunity_id,
            posting_id=posting_id,
            action="stage_move",
            detail=target_stage_name,
            dry_run=dry_run,
            success=success,
        )
    )
    return WriteResult(
        action="stage_move",
        opportunity_id=opportunity_id,
        detail=target_stage_name,
        dry_run=dry_run,
        would_send={"stage": target_stage_id} if dry_run else None,
    )
