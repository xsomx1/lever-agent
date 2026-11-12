"""Resume metadata + raw-byte download (T2.2).

The download must use the constructed opportunities-path endpoint, never the
`file.downloadUrl` field Lever returns — that path 403s for this key
(verified live 2026-08-18, see lever_client.py's download_resume_bytes docstring).
"""

import httpx
import pytest
import respx

from lever_agent.lever_client import LeverClient
from lever_agent.screening import fetch_resume_bytes


@respx.mock
async def test_get_resumes_returns_metadata_list():
    respx.get("https://api.lever.co/v1/opportunities/opp-1/resumes").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "resume-1",
                        "createdAt": 1000,
                        "file": {
                            "downloadUrl": "https://api.lever.co/v1/candidates/opp-1/resumes/resume-1/download"
                        },
                    }
                ]
            },
        )
    )

    async with LeverClient(api_key="fake-key") as client:
        resumes = await client.get_resumes("opp-1")

    assert resumes[0]["id"] == "resume-1"


@respx.mock
async def test_download_resume_bytes_uses_opportunities_path_not_download_url():
    route = respx.get(
        "https://api.lever.co/v1/opportunities/opp-1/resumes/resume-1/download"
    ).mock(return_value=httpx.Response(200, content=b"%PDF-fake-content"))
    # If the code ever followed file.downloadUrl instead, this route would never
    # be hit and the mock below would 404 unexpectedly.
    respx.get("https://api.lever.co/v1/candidates/opp-1/resumes/resume-1/download").mock(
        return_value=httpx.Response(403, json={"code": "ForbiddenError"})
    )

    async with LeverClient(api_key="fake-key") as client:
        data = await client.download_resume_bytes("opp-1", "resume-1")

    assert data == b"%PDF-fake-content"
    assert route.called


def _resumes_route(resumes):
    return respx.get("https://api.lever.co/v1/opportunities/opp-1/resumes").mock(
        return_value=httpx.Response(200, json={"data": resumes})
    )


@respx.mock
async def test_fetch_resume_bytes_skips_newer_record_without_file():
    # Live 2026-10-17: the newest record was a parsed profile with file=None,
    # and downloading it 400'd ("this resume does not include a file").
    _resumes_route(
        [
            {"id": "parsed-only", "createdAt": 2000, "file": None},
            {"id": "resume-pdf", "createdAt": 1000, "file": {"ext": ".pdf"}},
        ]
    )
    route = respx.get(
        "https://api.lever.co/v1/opportunities/opp-1/resumes/resume-pdf/download"
    ).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))

    async with LeverClient(api_key="fake-key") as client:
        data = await fetch_resume_bytes(client, "opp-1")

    assert data == b"%PDF-fake"
    assert route.called


@respx.mock
async def test_fetch_resume_bytes_raises_value_error_when_no_pdf():
    _resumes_route(
        [
            {"id": "parsed-only", "createdAt": 2000, "file": None},
            {"id": "resume-docx", "createdAt": 1000, "file": {"ext": ".docx"}},
        ]
    )

    async with LeverClient(api_key="fake-key") as client:
        with pytest.raises(ValueError, match="no PDF resume"):
            await fetch_resume_bytes(client, "opp-1")


@respx.mock
async def test_fetch_resume_bytes_rejects_pdf_ext_without_pdf_bytes():
    # Live 2026-10-17: a `.pdf` file that wasn't a PDF 400'd the API and killed the run.
    _resumes_route([{"id": "resume-pdf", "createdAt": 1000, "file": {"ext": ".pdf"}}])
    respx.get(
        "https://api.lever.co/v1/opportunities/opp-1/resumes/resume-pdf/download"
    ).mock(return_value=httpx.Response(200, content=b"PK\x03\x04not-a-pdf"))

    async with LeverClient(api_key="fake-key") as client:
        with pytest.raises(ValueError, match="not a valid PDF"):
            await fetch_resume_bytes(client, "opp-1")


@respx.mock
async def test_get_resumes_retries_read_timeout():
    route = respx.get("https://api.lever.co/v1/opportunities/opp-1/resumes").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"data": []})]
    )

    async with LeverClient(api_key="fake-key") as client:
        assert await client.get_resumes("opp-1") == []

    assert route.call_count == 2


@respx.mock
async def test_get_resumes_retries_bad_gateway():
    # Live 2026-10-17: a single 502 from Lever aborted two 200+ candidate screens.
    route = respx.get("https://api.lever.co/v1/opportunities/opp-1/resumes").mock(
        side_effect=[httpx.Response(502), httpx.Response(200, json={"data": []})]
    )

    async with LeverClient(api_key="fake-key") as client:
        assert await client.get_resumes("opp-1") == []

    assert route.call_count == 2
