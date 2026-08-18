"""get_my_postings must always request both distribution channels.

`state=published` alone omits internal-jobsite postings (docs/CONTEXT.md §3.3),
so both `distributionChannel=public` and `distributionChannel=internal` must be
sent on every call, unconditionally.
"""

import httpx
import respx

from lever_agent.config import MY_LEVER_UID
from lever_agent.lever_client import LeverClient


@respx.mock
async def test_get_my_postings_requests_both_distribution_channels():
    route = respx.get("https://api.lever.co/v1/postings").mock(
        return_value=httpx.Response(200, json={"data": [], "hasNext": False})
    )

    async with LeverClient(api_key="fake-key") as client:
        await client.get_my_postings()

    sent_params = route.calls[0].request.url.params
    assert sent_params.get_list("distributionChannel") == ["public", "internal"]


@respx.mock
async def test_get_my_postings_filters_to_owner_follower_or_hiring_manager():
    other_id = "not-me"
    postings = [
        {"id": "p1", "owner": {"id": MY_LEVER_UID}},
        {"id": "p2", "owner": {"id": other_id}, "followers": [{"id": MY_LEVER_UID}]},
        {"id": "p3", "owner": {"id": other_id}, "followers": [{"id": other_id}]},
        # ADR-0005: someone else owns it, but I'm the hiring manager — expanded shape.
        {"id": "p4", "owner": {"id": other_id}, "hiringManager": {"id": MY_LEVER_UID}},
        # hiringManager not expanded — comes back as a plain UID string.
        {"id": "p5", "owner": {"id": other_id}, "hiringManager": MY_LEVER_UID},
        {"id": "p6", "owner": {"id": other_id}, "hiringManager": {"id": other_id}},
    ]
    respx.get("https://api.lever.co/v1/postings").mock(
        return_value=httpx.Response(200, json={"data": postings, "hasNext": False})
    )

    async with LeverClient(api_key="fake-key") as client:
        mine = await client.get_my_postings()

    assert {p["id"] for p in mine} == {"p1", "p2", "p4", "p5"}


@respx.mock
async def test_get_my_postings_expands_hiring_manager():
    route = respx.get("https://api.lever.co/v1/postings").mock(
        return_value=httpx.Response(200, json={"data": [], "hasNext": False})
    )

    async with LeverClient(api_key="fake-key") as client:
        await client.get_my_postings()

    assert "hiringManager" in route.calls[0].request.url.params.get_list("expand")
