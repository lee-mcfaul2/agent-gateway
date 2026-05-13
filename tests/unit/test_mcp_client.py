from __future__ import annotations

import pytest
import respx
from httpx import Response

from ag_gateway.mcp_proxy.client import CallFail, CallOK, MCPClient


@pytest.fixture
async def client() -> MCPClient:
    c = MCPClient("http://kb-mcp.mcp.svc.cluster.local:8443")
    yield c
    await c.aclose()


@respx.mock
async def test_call_ok(client: MCPClient) -> None:
    respx.post("http://kb-mcp.mcp.svc.cluster.local:8443/v1/tools/search").mock(
        return_value=Response(200, json={"rows": [1, 2]})
    )
    res = await client.call("search", {"q": "x"})
    assert isinstance(res, CallOK)
    assert res.body == {"rows": [1, 2]}


@respx.mock
async def test_call_timeout(client: MCPClient) -> None:
    import httpx as _httpx

    respx.post("http://kb-mcp.mcp.svc.cluster.local:8443/v1/tools/search").mock(
        side_effect=_httpx.TimeoutException("slow")
    )
    res = await client.call("search", {})
    assert isinstance(res, CallFail) and res.error == "MCP_TIMEOUT"


@respx.mock
async def test_call_5xx(client: MCPClient) -> None:
    respx.post("http://kb-mcp.mcp.svc.cluster.local:8443/v1/tools/search").mock(
        return_value=Response(500)
    )
    res = await client.call("search", {})
    assert isinstance(res, CallFail) and res.error == "MCP_INTERNAL_ERROR"


@respx.mock
async def test_call_4xx(client: MCPClient) -> None:
    respx.post("http://kb-mcp.mcp.svc.cluster.local:8443/v1/tools/search").mock(
        return_value=Response(400, json={"error": "bad"})
    )
    res = await client.call("search", {})
    assert isinstance(res, CallFail) and res.error == "MCP_BAD_RESPONSE"
