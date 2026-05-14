"""LLM Guard sibling-service client. Fail-closed when enabled but unreachable.

Boot validation: enabled=True + empty base_url raises at init.
Disabled mode: returns ScanResult(action="allow", ...) immediately + increments
gateway_llm_guard_disabled_total{direction}.
Unreachable mode (enabled, 5xx after retry, network error, timeout): raises
LLMGuardUnavailable. Callers translate to 503 (inbound) or wrap_error (outbound)
and increment gateway_llm_guard_unavailable_total{direction}.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import httpx

from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import (
    LLM_GUARD_DISABLED_TOTAL,
    LLM_GUARD_UNAVAILABLE_TOTAL,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class ScanResult:
    action: Literal["allow", "flag", "block"]
    categories: list[str] = field(default_factory=list)
    spans: list[dict[str, object]] = field(default_factory=list)


class LLMGuardUnavailable(Exception):
    """Raised when LLM Guard is enabled but unreachable."""


class LLMGuardClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 2.0,
        enabled: bool = True,
    ) -> None:
        if enabled and not base_url:
            raise ValueError(
                "LLMGuardClient enabled=True requires a non-empty base_url. "
                "To disable for dev: pass enabled=False explicitly."
            )
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._enabled = enabled

    async def scan_inbound(self, text: str, request_uuid: str) -> ScanResult:
        return await self._scan(text, request_uuid, direction="inbound")

    async def scan_outbound_mcp_response(
        self, text: str, request_uuid: str, mcp: str, tool: str
    ) -> ScanResult:
        return await self._scan(
            text, request_uuid, direction="outbound", mcp=mcp, tool=tool
        )

    async def _scan(
        self,
        text: str,
        request_uuid: str,
        *,
        direction: str,
        mcp: str = "",
        tool: str = "",
    ) -> ScanResult:
        if not self._enabled:
            LLM_GUARD_DISABLED_TOTAL.labels(direction=direction).inc()
            return ScanResult(action="allow")

        payload = {
            "text": text,
            "request_uuid": request_uuid,
            "direction": direction,
            "mcp": mcp,
            "tool": tool,
        }
        last_status = 0
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                # One retry on 5xx
                for _attempt in range(2):
                    resp = await http.post(f"{self._base_url}/scan", json=payload)
                    last_status = resp.status_code
                    if resp.status_code < 500:
                        break
                if resp.status_code >= 400:
                    raise LLMGuardUnavailable(
                        f"LLM Guard returned {resp.status_code}"
                    )
                body = resp.json()
                return ScanResult(
                    action=body.get("action", "allow"),
                    categories=body.get("categories", []),
                    spans=body.get("spans", []),
                )
        except (httpx.HTTPError, ValueError) as exc:
            LLM_GUARD_UNAVAILABLE_TOTAL.labels(direction=direction).inc()
            log.warning(
                "llm_guard.unavailable",
                direction=direction,
                request_uuid=request_uuid,
                err=str(exc),
            )
            raise LLMGuardUnavailable(str(exc)) from exc
        except LLMGuardUnavailable:
            LLM_GUARD_UNAVAILABLE_TOTAL.labels(direction=direction).inc()
            log.warning(
                "llm_guard.unavailable",
                direction=direction,
                request_uuid=request_uuid,
                status=last_status,
            )
            raise
