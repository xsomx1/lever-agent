"""Write paths (T3.1-T3.4) — mocked httpx via respx, no real Lever calls, free.

Covers: dry-run never touches the network, real writes send the right
perform_as + body, the AI-Screened stage is blocked unconditionally, and every
path — dry-run or real, success or failure — lands in the audit log.
"""

import httpx
import pytest
import respx

from lever_agent.audit_log import AuditLog
from lever_agent.config import AI_SCREENED_STAGE_ID, MY_LEVER_UID, SCREENING_TAG
from lever_agent.lever_client import LeverClient
from lever_agent.rubric import Rubric
from lever_agent.screening import CandidateScore, ScreeningVerdict
from lever_agent.writes import (
    AIScreenedStageBlockedError,
    advance_stage,
    build_note_text,
    write_note,
    write_tag,
)

NOW_MS = 1_800_000_000_000

RUBRIC = Rubric.model_validate(
    {
        "posting_id": "p1",
        "posting_title": "Test Role",
        "criteria": [{"name": "depth", "description": "x", "weight": 1.0}],
    }
)


def _score(opportunity_id="opp-1", overall=8.3):
    verdict = ScreeningVerdict.model_validate(
        {
            "criterion_verdicts": [
                {"name": "depth", "score": 8, "evidence_quote": "x", "rationale": "y"}
            ],
            "summary": "solid candidate",
        }
    )
    return CandidateScore(
        opportunity_id=opportunity_id,
        name="Test Candidate",
        overall_score=overall,
        recommendation="strong yes",
        verdict=verdict,
    )


def test_build_note_text_is_labeled_and_compact():
    text = build_note_text(RUBRIC, _score())
    assert text.startswith("[lever-agent]")
    assert "8.3" in text
    assert "depth: 8/10" in text
    assert "solid candidate" in text


@respx.mock
async def test_write_note_dry_run_never_calls_lever(tmp_path):
    route = respx.post("https://api.lever.co/v1/opportunities/opp-1/notes")
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        result = await write_note(
            client, audit, "post-1", _score(), "note body", now_ms=NOW_MS, dry_run=True
        )

    assert route.call_count == 0
    assert result.dry_run is True
    assert result.would_send == {"value": "note body"}

    entries = AuditLog(tmp_path / "t.db").recent()
    assert entries[0].action == "note"
    assert entries[0].dry_run is True
    assert entries[0].success is True


@respx.mock
async def test_write_note_real_sends_perform_as_and_body(tmp_path):
    route = respx.post("https://api.lever.co/v1/opportunities/opp-1/notes").mock(
        return_value=httpx.Response(200, json={"data": {"id": "note-1"}})
    )
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        result = await write_note(
            client, audit, "post-1", _score(), "note body", now_ms=NOW_MS, dry_run=False
        )

    assert route.called
    request = route.calls[0].request
    assert request.url.params["perform_as"] == MY_LEVER_UID
    import json

    assert json.loads(request.content) == {"value": "note body"}
    assert result.dry_run is False


@respx.mock
async def test_write_note_failure_logs_success_false(tmp_path):
    respx.post("https://api.lever.co/v1/opportunities/opp-1/notes").mock(
        return_value=httpx.Response(500, json={"code": "ServerError"})
    )
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        with pytest.raises(httpx.HTTPStatusError):
            await write_note(client, audit, "post-1", _score(), "note body", now_ms=NOW_MS)

    entries = AuditLog(tmp_path / "t.db").recent()
    assert entries[0].success is False
    assert entries[0].dry_run is False


@respx.mock
async def test_write_tag_dry_run_never_calls_lever(tmp_path):
    route = respx.post("https://api.lever.co/v1/opportunities/opp-1/addTags")
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        result = await write_tag(client, audit, "post-1", "opp-1", now_ms=NOW_MS, dry_run=True)

    assert route.call_count == 0
    assert result.would_send == {"tags": [SCREENING_TAG]}


@respx.mock
async def test_write_tag_real_sends_fixed_constant(tmp_path):
    route = respx.post("https://api.lever.co/v1/opportunities/opp-1/addTags").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        await write_tag(client, audit, "post-1", "opp-1", now_ms=NOW_MS, dry_run=False)

    import json

    assert json.loads(route.calls[0].request.content) == {"tags": [SCREENING_TAG]}


@respx.mock
async def test_advance_stage_dry_run_never_calls_lever(tmp_path):
    route = respx.put("https://api.lever.co/v1/opportunities/opp-1/stage")
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        result = await advance_stage(
            client, audit, "post-1", "opp-1", "interview-stage-id", "Interview",
            now_ms=NOW_MS, dry_run=True,
        )

    assert route.call_count == 0
    assert result.would_send == {"stage": "interview-stage-id"}


@respx.mock
async def test_advance_stage_real_sends_perform_as_and_body(tmp_path):
    route = respx.put("https://api.lever.co/v1/opportunities/opp-1/stage").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        await advance_stage(
            client, audit, "post-1", "opp-1", "interview-stage-id", "Interview", now_ms=NOW_MS
        )

    request = route.calls[0].request
    assert request.url.params["perform_as"] == MY_LEVER_UID


@respx.mock
async def test_advance_stage_blocks_ai_screened_target_dry_run_and_real(tmp_path):
    route = respx.put("https://api.lever.co/v1/opportunities/opp-1/stage")
    audit = AuditLog(tmp_path / "t.db")
    async with LeverClient(api_key="fake-key") as client:
        for dry_run in (True, False):
            with pytest.raises(AIScreenedStageBlockedError, match="T0.7"):
                await advance_stage(
                    client, audit, "post-1", "opp-1", AI_SCREENED_STAGE_ID, "AI Screened",
                    now_ms=NOW_MS, dry_run=dry_run,
                )

    assert route.call_count == 0
