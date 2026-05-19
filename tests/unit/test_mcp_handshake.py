from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from dataclasses import dataclass

from ag_gateway.mcp_proxy.handshake import handshake_one
from ag_gateway.mcp_proxy.registry import MCPRegistry


@dataclass(frozen=True)
class _DigestEntry:
    """Test double: an MCP registry entry that DOES carry a comparable
    expected aggregate schema_digest (the production MCPEntry intentionally
    does not — see handshake.py for why). Used to exercise the degrade-on-
    mismatch / proceed-on-match branches."""

    name: str
    schema_version: str
    schema_digest: str


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
async def test_handshake_ok_with_digest_unverified(registry: MCPRegistry) -> None:
    """MCP returns a schema_digest but the registry entry has no comparable
    expected aggregate → proceed (healthy), digest left unverified."""
    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        return_value=Response(
            200, json={"schema_version": "1.0.0", "schema_digest": "sha256:deadbeef"}
        )
    )
    ok = await handshake_one(registry.get("kb"), registry)
    assert ok is True
    assert registry.state("kb") == "healthy"


@respx.mock
async def test_handshake_digest_match(registry: MCPRegistry) -> None:
    """Registry entry carries a comparable digest and the MCP matches it
    → healthy."""
    entry = _DigestEntry(
        name="kb", schema_version="1.0.0", schema_digest="sha256:abc123"
    )
    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        return_value=Response(
            200, json={"schema_version": "1.0.0", "schema_digest": "sha256:abc123"}
        )
    )
    ok = await handshake_one(entry, registry)  # type: ignore[arg-type]
    assert ok is True
    assert registry.state("kb") == "healthy"


@respx.mock
async def test_handshake_digest_mismatch(registry: MCPRegistry) -> None:
    """Registry entry carries a comparable digest and the MCP disagrees
    → degraded."""
    entry = _DigestEntry(
        name="kb", schema_version="1.0.0", schema_digest="sha256:expected"
    )
    respx.get("http://kb-mcp.mcp.svc.cluster.local:8443/handshake").mock(
        return_value=Response(
            200, json={"schema_version": "1.0.0", "schema_digest": "sha256:drifted"}
        )
    )
    ok = await handshake_one(entry, registry)  # type: ignore[arg-type]
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
