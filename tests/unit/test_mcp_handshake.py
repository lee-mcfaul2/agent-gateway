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
    """Build a minimal v1.0-shape bundle manifest for the 'kb' MCP."""
    (tmp_path / "bundle-manifest.json").write_text(
        json.dumps(
            {
                "bundle_version": "1.0.0",
                "schema_library_version": "1.0.0",
                "build": {
                    "timestamp": "2026-05-14T00:00:00Z",
                    "source_commit": "test",
                    "builder_id": "test",
                },
                "envelope_cost_caps": {
                    "max_iterations": 8,
                    "max_wallclock_ms": 300000,
                    "max_cost_usd": 1,
                },
                "services": [
                    {
                        "mcp": "kb",
                        "tools": [
                            {
                                "name": "search",
                                "request_digest": "sha256:aaa",
                                "response_digest": "sha256:bbb",
                                "requires_permissions": ["kb:read"],
                            }
                        ],
                    }
                ],
            }
        )
    )
    return MCPRegistry.from_bundle(tmp_path)


@respx.mock
async def test_handshake_ok(registry: MCPRegistry) -> None:
    """MCP replies with the correct bundle version → healthy."""
    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        return_value=Response(200, json={"schema_version": "1.0.0"})
    )
    ok = await handshake_one(registry.get("kb"), registry)
    assert ok is True
    assert registry.state("kb") == "healthy"


@respx.mock
async def test_handshake_version_mismatch(registry: MCPRegistry) -> None:
    """MCP replies with a different bundle version → degraded."""
    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        return_value=Response(200, json={"schema_version": "0.9.0"})
    )
    ok = await handshake_one(registry.get("kb"), registry)
    assert ok is False
    assert registry.state("kb") == "degraded"


@respx.mock
async def test_handshake_unreachable(registry: MCPRegistry) -> None:
    """MCP is not reachable → degraded."""
    import httpx as _httpx

    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        side_effect=_httpx.ConnectError("nope")
    )
    ok = await handshake_one(registry.get("kb"), registry)
    assert ok is False
    assert registry.state("kb") == "degraded"
