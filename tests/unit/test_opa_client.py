from __future__ import annotations

import pytest
import respx
from httpx import Response

from ag_gateway.hooks.opa_client import OPAClient


@pytest.fixture
async def client() -> OPAClient:
    c = OPAClient("http://opa:8181")
    yield c
    await c.aclose()


@respx.mock
async def test_allow(client: OPAClient) -> None:
    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        return_value=Response(200, json={"result": {"allow": True, "reason": "ok"}})
    )
    d = await client.decide({"user": "x", "mcp": "audit_db", "tool": "search"})
    assert d.allow is True
    assert d.reason == "ok"


@respx.mock
async def test_deny_with_reason(client: OPAClient) -> None:
    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        return_value=Response(
            200,
            json={
                "result": {
                    "allow": False,
                    "reason": "missing_permission:audit:read",
                }
            },
        )
    )
    d = await client.decide({"user": "x"})
    assert d.allow is False
    assert d.reason == "missing_permission:audit:read"


@respx.mock
async def test_500_is_deny(client: OPAClient) -> None:
    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        return_value=Response(500)
    )
    d = await client.decide({"user": "x"})
    assert d.allow is False
    assert d.reason == "opa_http_500"


@respx.mock
async def test_timeout_is_deny(client: OPAClient) -> None:
    import httpx as _httpx

    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        side_effect=_httpx.TimeoutException("slow")
    )
    d = await client.decide({"user": "x"})
    assert d.allow is False
    assert d.reason == "opa_timeout"


@respx.mock
async def test_missing_result_field_is_deny(client: OPAClient) -> None:
    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        return_value=Response(200, json={})
    )
    d = await client.decide({"user": "x"})
    assert d.allow is False
    assert d.reason == "default_deny"
