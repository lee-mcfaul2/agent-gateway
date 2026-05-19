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
        SCHEMA_FAILURES_TOTAL.labels(
            type="mcp_handshake", reason="unreachable", mcp=entry.name
        ).inc()
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
        SCHEMA_FAILURES_TOTAL.labels(
            type="mcp_handshake", reason="bad_json", mcp=entry.name
        ).inc()
        return False

    # In the v1.0 bundle model the gateway is the schema source of truth.
    # We verify the MCP advertises the same bundle version we loaded.
    if body.get("schema_version") != entry.schema_version:
        registry.set_state(entry.name, "degraded")
        SCHEMA_FAILURES_TOTAL.labels(
            type="mcp_handshake", reason="version_mismatch", mcp=entry.name
        ).inc()
        return False

    # schema_digest verification.
    #
    # The MCP's `/handshake` returns an aggregate `schema_digest` computed over
    # ITS tool set (agent-sql-mcp/internal/schemas/loader.go: sha256 of
    # `tool\n + canonicalJSON(req)\n + canonicalJSON(resp)\n` per tool, scoped
    # to that one MCP, with Go json.Marshal canonicalization).
    #
    # The gateway-side digest (prompts/bundle_view.py: BundleView.digest) is a
    # sha256 over RAW bytes of the envelope schemas PLUS every tool's
    # request/response across the WHOLE bundle, with \x00 separators and no
    # canonicalization. Different scope, pre-image, and normalization — the two
    # aggregates are incomparable by design, and the bundle manifest /
    # MCPEntry carry no per-MCP aggregate digest to compare against.
    #
    # So: if the registry ever exposes a directly comparable expected aggregate
    # digest for this MCP, degrade on mismatch (same pattern as version_mismatch).
    # Otherwise we cannot soundly compare; record what the MCP advertised and
    # emit a `schema_digest_unverified` warning instead of breaking the working
    # path on an incomparable-by-design value.
    mcp_digest = body.get("schema_digest")
    expected_digest = getattr(entry, "schema_digest", None)
    if expected_digest is not None and mcp_digest is not None:
        if mcp_digest != expected_digest:
            log.warning(
                "mcp.handshake_digest_mismatch",
                mcp=entry.name,
                expected=expected_digest,
                got=mcp_digest,
            )
            registry.set_state(entry.name, "degraded")
            SCHEMA_FAILURES_TOTAL.labels(
                type="mcp_handshake", reason="digest_mismatch", mcp=entry.name
            ).inc()
            return False
    else:
        log.warning(
            "mcp.schema_digest_unverified",
            mcp=entry.name,
            mcp_digest=mcp_digest,
            reason="no_comparable_aggregate_digest",
        )

    registry.set_state(entry.name, "healthy")
    return True


async def handshake_all(registry: MCPRegistry) -> dict[str, bool]:
    """Call handshake_one for every MCP. Returns {name: ok}."""
    results = await asyncio.gather(
        *[handshake_one(registry.get(n), registry) for n in registry.names()],
        return_exceptions=False,
    )
    return dict(zip(registry.names(), results, strict=False))
