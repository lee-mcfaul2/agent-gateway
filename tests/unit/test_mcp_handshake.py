from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from ag_gateway.mcp_proxy.handshake import handshake_one
from ag_gateway.mcp_proxy.registry import MCPRegistry


@pytest.fixture
def registry(tmp_path: Path) -> MCPRegistry:
    p = tmp_path / "mcps"
    p.mkdir()
    (p / "catalog.json").write_text(
        json.dumps(
            {
                "mcps": [
                    {
                        "name": "kb",
                        "spiffe": "spiffe://x/kb",
                        "schema_version": "v1",
                        "schema_digest": "sha256:abc",
                    }
                ]
            }
        )
    )
    return MCPRegistry.from_bundle(tmp_path)


@respx.mock
async def test_handshake_ok(registry: MCPRegistry) -> None:
    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        return_value=Response(200, json={"schema_version": "v1", "schema_digest": "sha256:abc"})
    )
    ok = await handshake_one(registry.get("kb"), registry)
    assert ok is True
    assert registry.state("kb") == "healthy"


@respx.mock
async def test_handshake_digest_mismatch(registry: MCPRegistry) -> None:
    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        return_value=Response(200, json={"schema_version": "v1", "schema_digest": "sha256:WRONG"})
    )
    ok = await handshake_one(registry.get("kb"), registry)
    assert ok is False
    assert registry.state("kb") == "degraded"


@respx.mock
async def test_handshake_unreachable(registry: MCPRegistry) -> None:
    import httpx as _httpx

    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        side_effect=_httpx.ConnectError("nope")
    )
    ok = await handshake_one(registry.get("kb"), registry)
    assert ok is False
    assert registry.state("kb") == "degraded"
