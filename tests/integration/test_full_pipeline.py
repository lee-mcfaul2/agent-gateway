from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_opa_allow_known_permission(integration_stack: dict[str, str]) -> None:
    """Smoke test: post a decision query directly to OPA with our shipped policy."""
    import httpx

    url = integration_stack["opa"] + "/v1/data/ag_gateway/authz/decision"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            json={
                "input": {
                    "user": {"sub": "alice", "permissions": ["kb:read"]},
                    "mcp": "kb",
                    "tool": "search",
                }
            },
        )
    assert r.status_code == 200
    assert r.json()["result"]["allow"] is True


@pytest.mark.asyncio
async def test_opa_deny_missing_permission(integration_stack: dict[str, str]) -> None:
    import httpx

    url = integration_stack["opa"] + "/v1/data/ag_gateway/authz/decision"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            json={
                "input": {
                    "user": {"sub": "alice", "permissions": []},
                    "mcp": "audit_db",
                    "tool": "search",
                }
            },
        )
    body = r.json()
    assert body["result"]["allow"] is False
    assert body["result"]["reason"].startswith("missing_permission")


@pytest.mark.asyncio
async def test_tokenizer_mock_init(integration_stack: dict[str, str]) -> None:
    import httpx

    async with httpx.AsyncClient() as client:
        r = await client.post(
            integration_stack["tokenizer"] + "/v1/init_request",
            json={"request_uuid": "11111111-1111-1111-1111-111111111111", "ttl_seconds": 60},
        )
    assert r.status_code == 200
    assert r.json()["request_uuid"] == "11111111-1111-1111-1111-111111111111"
