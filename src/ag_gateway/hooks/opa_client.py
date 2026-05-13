from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ag_gateway.obs.metrics import OPA_ERRORS_TOTAL


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str  # "missing_permission:audit:read" / "attribute_mismatch" / "default_deny"


class OPAClient:
    """Async client for the OPA sidecar."""

    DEFAULT_PATH = "/v1/data/ag_gateway/authz/decision"

    def __init__(self, base_url: str, timeout_seconds: float = 0.250) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def decide(self, input_doc: dict[str, Any], path: str = DEFAULT_PATH) -> Decision:
        """Query OPA. Any error (timeout, 5xx, missing fields) is treated as deny."""
        try:
            r = await self._client.post(path, json={"input": input_doc})
        except httpx.TimeoutException:
            OPA_ERRORS_TOTAL.labels(reason="timeout").inc()
            return Decision(False, "opa_timeout")
        except httpx.HTTPError as exc:
            OPA_ERRORS_TOTAL.labels(reason="network").inc()
            return Decision(False, f"opa_error:{exc.__class__.__name__}")

        if r.status_code != 200:
            OPA_ERRORS_TOTAL.labels(reason=f"http_{r.status_code}").inc()
            return Decision(False, f"opa_http_{r.status_code}")

        try:
            result = r.json().get("result", {})
        except ValueError:
            OPA_ERRORS_TOTAL.labels(reason="bad_json").inc()
            return Decision(False, "opa_bad_json")

        allow = bool(result.get("allow", False))
        reason = str(result.get("reason", "default_deny"))
        return Decision(allow=allow, reason=reason)
