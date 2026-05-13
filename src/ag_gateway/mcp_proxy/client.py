from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from ag_gateway.mcp_proxy.registry import MCPEntry

ClientError = Literal[
    "MCP_UNAVAILABLE",
    "MCP_TIMEOUT",
    "MCP_INTERNAL_ERROR",
    "MCP_BAD_RESPONSE",
]


@dataclass(frozen=True)
class CallOK:
    body: Any


@dataclass(frozen=True)
class CallFail:
    error: ClientError
    reason: str


CallResult = CallOK | CallFail


class MCPClient:
    """One HTTP client per MCP, reused across calls."""

    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base, timeout=httpx.Timeout(timeout_seconds)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(
        self, tool: str, args: dict[str, Any], headers: dict[str, str] | None = None
    ) -> CallResult:
        try:
            r = await self._client.post(f"/v1/tools/{tool}", json=args, headers=headers or {})
        except httpx.TimeoutException:
            return CallFail("MCP_TIMEOUT", "client timeout")
        except httpx.HTTPError as exc:
            return CallFail("MCP_UNAVAILABLE", f"transport: {exc.__class__.__name__}")
        if r.status_code >= 500:
            return CallFail("MCP_INTERNAL_ERROR", f"status={r.status_code}")
        if r.status_code >= 400:
            return CallFail("MCP_BAD_RESPONSE", f"status={r.status_code}")
        try:
            body = r.json()
        except ValueError:
            return CallFail("MCP_BAD_RESPONSE", "non-json response")
        return CallOK(body=body)


class MCPClientPool:
    """One client per MCP name; lazily constructed."""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    def for_(self, mcp: MCPEntry) -> MCPClient:
        """Returns or creates a client for this MCP. Base URL derived from SPIFFE name."""
        if mcp.name not in self._clients:
            base = f"http://{mcp.name}-mcp.mcp.svc.cluster.local:8443"
            self._clients[mcp.name] = MCPClient(base)
        return self._clients[mcp.name]

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.aclose()
