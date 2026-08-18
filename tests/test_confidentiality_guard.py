"""This key 403s on `confidentiality` (verified 2026-08-18, docs/PLAN.md).

A stray `confidentiality` param must fail the request outright, not degrade
silently. Guard both directions: the client's own methods never send it, and
if it's ever passed in explicitly it's rejected before hitting the network.
"""

import inspect

import pytest
import respx

from lever_agent.lever_client import LeverClient


@respx.mock
async def test_get_rejects_confidentiality_param_before_sending():
    route = respx.get("https://api.lever.co/v1/postings")

    async with LeverClient(api_key="fake-key") as client:
        with pytest.raises(ValueError, match="confidentiality"):
            await client._get("postings", {"confidentiality": "all"})

    assert route.call_count == 0


def test_get_my_postings_signature_has_no_confidentiality_kwarg():
    signature = inspect.signature(LeverClient.get_my_postings)
    assert "confidentiality" not in signature.parameters


@respx.mock
async def test_get_my_postings_never_emits_confidentiality():
    import httpx

    route = respx.get("https://api.lever.co/v1/postings").mock(
        return_value=httpx.Response(200, json={"data": [], "hasNext": False})
    )

    async with LeverClient(api_key="fake-key") as client:
        await client.get_my_postings()

    assert "confidentiality" not in route.calls[0].request.url.params
