"""Async Lever API client.

Written fresh from the public docs (https://hire.lever.co/developer/documentation) —
deliberately NOT copied from the internal `lever-deep-sync` client. See docs/CONTEXT.md
§1 and the security notes in docs/PLAN.md.

Design points, all from docs/CONTEXT.md §3:
- Auth is HTTP Basic, API key as username, blank password.
- Rate limit is 10 req/s per key, bursts to 20. 429/503 carry no `Retry-After` —
  back off blind, with jitter.
- Pagination is an opaque cursor named `offset` in the request but returned as
  `next` in the response, alongside `hasNext`. Pass `next` back verbatim.
- This key has NO confidential-data access (verified 2026-08-18) — passing
  `confidentiality=all` 403s rather than degrading. So the client never accepts
  or emits a `confidentiality` parameter at all; there is no kwarg for it.
- `state=published` alone omits internal-jobsite postings — pass both
  `distributionChannel=public` and `distributionChannel=internal`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from lever_agent.config import LEVER_API_BASE, LEVER_RATE_LIMIT, MY_LEVER_UID

_RETRYABLE_STATUS_CODES = {429, 503}


def _is_retryable(exc: BaseException) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in _RETRYABLE_STATUS_CODES
    )


class LeverClient:
    """Thin async wrapper around the Lever REST API.

    Read-only in this module by design — Epic 0 only needs GET endpoints.
    Write methods (notes, tags, stage moves) land in Epic 3, gated on human
    confirmation per ADR-0002.
    """

    def __init__(self, api_key: str, *, base_url: str = LEVER_API_BASE) -> None:
        self._semaphore = asyncio.Semaphore(LEVER_RATE_LIMIT)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            auth=httpx.BasicAuth(api_key, ""),
            timeout=30.0,
        )

    async def __aenter__(self) -> "LeverClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # No `confidentiality` param is accepted anywhere in this class — see
        # module docstring. Guard against it slipping in via **params misuse.
        if params and "confidentiality" in params:
            raise ValueError(
                "This Lever key has no confidential-data access; "
                "'confidentiality' must never be sent (see docs/PLAN.md)"
            )
        async with self._semaphore:
            response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    async def _get_bytes(self, path: str) -> bytes:
        """Like `_get`, but for endpoints that return a raw file, not JSON."""
        async with self._semaphore:
            response = await self._client.get(path)
        response.raise_for_status()
        return response.content

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    async def _post(
        self, path: str, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if params and "confidentiality" in params:
            raise ValueError(
                "This Lever key has no confidential-data access; "
                "'confidentiality' must never be sent (see docs/PLAN.md)"
            )
        async with self._semaphore:
            response = await self._client.post(path, params=params, json=json_body)
        response.raise_for_status()
        return response.json()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    async def _put(
        self, path: str, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if params and "confidentiality" in params:
            raise ValueError(
                "This Lever key has no confidential-data access; "
                "'confidentiality' must never be sent (see docs/PLAN.md)"
            )
        async with self._semaphore:
            response = await self._client.put(path, params=params, json=json_body)
        response.raise_for_status()
        return response.json()

    async def create_note(self, opportunity_id: str, text: str) -> dict[str, Any]:
        """POST /opportunities/:id/notes, attributed via perform_as (T3.1).

        Body shape (`{"value": text}`) follows Lever's documented note-creation
        convention. This key can't read notes back to double-check (GET .../notes
        403s, expand=notes 400s — see docs/PLAN.md Epic 3 context), so this is
        confirmed by the one live write the plan calls for, not by a prior
        read-only probe like everything else in this client.
        """
        return await self._post(
            f"opportunities/{opportunity_id}/notes",
            params={"perform_as": MY_LEVER_UID},
            json_body={"value": text},
        )

    async def add_tags(self, opportunity_id: str, tags: list[str]) -> dict[str, Any]:
        """POST /opportunities/:id/addTags, attributed via perform_as (T3.2)."""
        return await self._post(
            f"opportunities/{opportunity_id}/addTags",
            params={"perform_as": MY_LEVER_UID},
            json_body={"tags": tags},
        )

    async def update_stage(self, opportunity_id: str, stage_id: str) -> dict[str, Any]:
        """PUT /opportunities/:id/stage, attributed via perform_as (T3.3).

        Callers must apply the AI-Screened guard and the explicit-confirmation
        prompt themselves (see writes.py) — this method only makes the call.
        """
        return await self._put(
            f"opportunities/{opportunity_id}/stage",
            params={"perform_as": MY_LEVER_UID},
            json_body={"stage": stage_id},
        )

    async def list_paginated(
        self, path: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every record from a Lever list endpoint, following the cursor.

        The cursor param is named `offset` on the request but returned as
        `next` in the response body, alongside `hasNext`. It is passed back
        verbatim — never synthesized or decoded.
        """
        request_params = dict(params or {})
        while True:
            page = await self._get(path, request_params)
            for record in page.get("data", []):
                yield record
            if not page.get("hasNext"):
                return
            request_params = dict(params or {})
            request_params["offset"] = page["next"]

    async def get_my_postings(self) -> list[dict[str, Any]]:
        """Postings where I'm the owner, a follower, or the hiring manager (T0.5, ADR-0005).

        `state=published` alone omits internal-jobsite postings, so both
        distribution channels are requested explicitly. `confidentiality` is
        left off entirely — this key has no confidential-data access.
        """
        params = {
            "expand": ["owner", "followers", "hiringManager"],
            "distributionChannel": ["public", "internal"],
        }
        postings = [p async for p in self.list_paginated("postings", params)]
        return [p for p in postings if _is_mine(p)]

    async def get_opportunities_for_posting(self, posting_id: str) -> list[dict[str, Any]]:
        """All opportunities (any stage, any pipeline) tied to one posting.

        Live-verified 2026-08-18: each opportunity carries `lastAdvancedAt`, which
        matches its last `stageChanges[].updatedAt` exactly — that is the reliable
        "entered current stage" timestamp for SLA math (T1.1). The top-level
        `updatedAt` field does not match it and must never be used for that
        (docs/CONTEXT.md §3.1's trap).
        """
        params = {"posting_id": posting_id, "limit": 100}
        return [opp async for opp in self.list_paginated("opportunities", params)]

    async def get_disposition_stages(self) -> dict[str, Any]:
        """Full stage list with `id`, `text`, `rank`, `pipeline`, in pipeline order.

        `GET /disposition_stages` is NOT a paginated list endpoint — the response
        is a single object: `{"data": {"stages": [...], ...}}`. `GET /stages`
        returns only `{id, text}` with no ordering, which is why this endpoint is
        used instead (docs/CONTEXT.md §3, trap 6).
        """
        response = await self._get("disposition_stages")
        return response["data"]

    async def get_resumes(self, opportunity_id: str) -> list[dict[str, Any]]:
        """Resume metadata for one opportunity — NOT the file bytes (T2.2).

        `GET /opportunities/:id/resumes` is not a paginated list endpoint here
        (small, unpaginated array), so this reads `data` directly rather than
        going through `list_paginated`.
        """
        response = await self._get(f"opportunities/{opportunity_id}/resumes")
        return response["data"]

    async def download_resume_bytes(self, opportunity_id: str, resume_id: str) -> bytes:
        """Raw PDF bytes for one resume (T2.2).

        Live-verified 2026-08-18: the `file.downloadUrl` field returned by
        `get_resumes()` points at `/v1/candidates/.../resumes/.../download`,
        which 403s for this key (`ForbiddenError: no access to this endpoint`).
        The path constructed here — `/v1/opportunities/:id/resumes/:resumeId/download`,
        exactly as docs/PLAN.md T2.2 describes — works and returns raw
        `application/pdf` bytes. Never follow `file.downloadUrl`.
        """
        return await self._get_bytes(
            f"opportunities/{opportunity_id}/resumes/{resume_id}/download"
        )


def _is_mine(posting: dict[str, Any]) -> bool:
    """Owner, follower, or hiring manager — see ADR-0005.

    `hiringManager` is a plain UID string unless `expand=hiringManager` was
    requested, in which case it comes back as a user object like `owner` and
    `followers` — handle both shapes since callers may not always expand it.
    """
    owner = posting.get("owner")
    if isinstance(owner, dict) and owner.get("id") == MY_LEVER_UID:
        return True
    for follower in posting.get("followers") or []:
        if isinstance(follower, dict) and follower.get("id") == MY_LEVER_UID:
            return True
    hiring_manager = posting.get("hiringManager")
    if isinstance(hiring_manager, dict):
        return hiring_manager.get("id") == MY_LEVER_UID
    return hiring_manager == MY_LEVER_UID
