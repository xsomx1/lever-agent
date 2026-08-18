"""Stage id → display name / rank lookup, built from a live disposition_stages call.

Fetched fresh each digest run rather than hardcoded — the Confluence pipeline
guide was already found stale by two stages (docs/CONTEXT.md §2), so this
agent doesn't trust a static copy either.
"""

from __future__ import annotations

from typing import Any, TypedDict

from lever_agent.lever_client import LeverClient


class StageInfo(TypedDict):
    text: str
    rank: float
    pipeline: str


async def get_stage_lookup(client: LeverClient) -> dict[str, StageInfo]:
    data = await client.get_disposition_stages()
    return {
        stage["id"]: StageInfo(text=stage["text"], rank=stage["rank"], pipeline=stage["pipeline"])
        for stage in data.get("stages", [])
    }


def stage_name(lookup: dict[str, StageInfo], stage_id: str) -> str:
    info: Any = lookup.get(stage_id)
    return info["text"] if info else stage_id
