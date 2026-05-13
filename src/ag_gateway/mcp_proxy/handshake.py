from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ag_gateway.mcp_proxy.registry import MCPEntry, MCPRegistry
from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import SCHEMA_FAILURES_TOTAL


log = get_logger(__name__)


async def handshake_one(entry: MCPEntry, registry: MCPRegistry) -> bool:
    """Call /handshake on the MCP; return True on success."""
    base = f"http://{entry.name}-mcp.mcp.svc.cluster.local:8443"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get(f"{base}/handshake")
    except httpx.HTTPError as exc:
        log.warning("mcp.handshake_unreachable", mcp=entry.name, err=str(exc))
        registry.set_state(entry.name, "degraded")
        SCHEMA_FAILURES_TOTAL.labels(type="mcp_handshake", reason="unreachable", mcp=entry.name).inc()
        return False

    if r.status_code != 200:
        log.warning("mcp.handshake_bad_status", mcp=entry.name, status=r.status_code)
        registry.set_state(entry.name, "degraded")
        SCHEMA_FAILURES_TOTAL.labels(
            type="mcp_handshake", reason=f"http_{r.status_code}", mcp=entry.name
        ).inc()
        return False

    try:
        body: dict[str, Any] = r.json()
    except ValueError:
        registry.set_state(entry.name, "degraded")
        SCHEMA_FAILURES_TOTAL.labels(type="mcp_handshake", reason="bad_json", mcp=entry.name).inc()
        return False

    if body.get("schema_version") != entry.schema_version:
        registry.set_state(entry.name, "degraded")
        SCHEMA_FAILURES_TOTAL.labels(
            type="mcp_handshake", reason="version_mismatch", mcp=entry.name
        ).inc()
        return False

    if body.get("schema_digest") != entry.schema_digest:
        registry.set_state(entry.name, "degraded")
        SCHEMA_FAILURES_TOTAL.labels(
            type="mcp_handshake", reason="digest_mismatch", mcp=entry.name
        ).inc()
        return False

    registry.set_state(entry.name, "healthy")
    return True


async def handshake_all(registry: MCPRegistry) -> dict[str, bool]:
    """Call handshake_one for every MCP. Returns {name: ok}."""
    results = await asyncio.gather(
        *[handshake_one(registry.get(n), registry) for n in registry.names()],
        return_exceptions=False,
    )
    return dict(zip(registry.names(), results))
