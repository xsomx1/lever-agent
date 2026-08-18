"""Resume metadata + raw-byte download (T2.2).

The download must use the constructed opportunities-path endpoint, never the
`file.downloadUrl` field Lever returns — that path 403s for this key
(verified live 2026-08-18, see lever_client.py's download_resume_bytes docstring).
"""

import httpx
import respx

from lever_agent.lever_client import LeverClient


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
