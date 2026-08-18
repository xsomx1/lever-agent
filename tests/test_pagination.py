"""Cursor pagination must follow hasNext/next verbatim, across multiple pages."""

import httpx
import respx

from lever_agent.lever_client import LeverClient


@respx.mock
async def test_list_paginated_follows_cursor_across_pages():
    route = respx.get("https://api.lever.co/v1/postings")
    route.side_effect = [
        httpx.Response(
            200,
            json={"data": [{"id": "a"}, {"id": "b"}], "hasNext": True, "next": "cursor-1"},
        ),
        httpx.Response(
            200,
            json={"data": [{"id": "c"}], "hasNext": True, "next": "cursor-2"},
        ),
        httpx.Response(
            200,
            json={"data": [{"id": "d"}], "hasNext": False},
        ),
    ]

    async with LeverClient(api_key="fake-key") as client:
        records = [record async for record in client.list_paginated("postings")]

    assert [r["id"] for r in records] == ["a", "b", "c", "d"]

    # The cursor must be passed back verbatim as `offset`, never synthesized.
    requests = [call.request for call in route.calls]
    assert "offset" not in requests[0].url.params
    assert requests[1].url.params["offset"] == "cursor-1"
    assert requests[2].url.params["offset"] == "cursor-2"


@respx.mock
async def test_list_paginated_stops_when_has_next_is_false():
    respx.get("https://api.lever.co/v1/postings").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "only"}], "hasNext": False})
    )

    async with LeverClient(api_key="fake-key") as client:
        records = [record async for record in client.list_paginated("postings")]

    assert len(records) == 1
