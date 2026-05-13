from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ag_gateway.obs.metrics import DETOKENIZE_FAILURES_TOTAL


class TokenizerError(Exception):
    """Raised when the tokenizer returns a non-2xx response we can classify."""

    def __init__(self, error_type: str, message: str, status: int) -> None:
        super().__init__(f"{error_type}: {message}")
        self.error_type = error_type
        self.message = message
        self.status = status


class TokenizerUnavailable(Exception):
    """Raised on network failure / 503."""


@dataclass(frozen=True)
class InitResult:
    request_uuid: str
    expires_at: str


class TokenizerClient:
    """Async HTTP client for pii-tokenizer."""

    def __init__(self, base_url: str, timeout_seconds: float = 1.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def init_request(self, request_uuid: str, ttl_seconds: int) -> InitResult:
        try:
            r = await self._client.post(
                "/v1/init_request",
                json={"request_uuid": request_uuid, "ttl_seconds": ttl_seconds},
            )
        except httpx.HTTPError as exc:
            raise TokenizerUnavailable(str(exc)) from exc
        if r.status_code >= 500:
            raise TokenizerUnavailable(f"status={r.status_code}")
        if r.status_code not in (200, 201):
            body = _parse_error(r)
            raise TokenizerError(body["error_type"], body["message"], r.status_code)
        data = r.json()
        return InitResult(request_uuid=data["request_uuid"], expires_at=data["expires_at"])

    async def tokenize(self, request_uuid: str, type_: str, plaintext: str) -> str:
        try:
            r = await self._client.post(
                "/v1/tokenize",
                json={"request_uuid": request_uuid, "type": type_, "plaintext": plaintext},
            )
        except httpx.HTTPError as exc:
            raise TokenizerUnavailable(str(exc)) from exc
        if r.status_code >= 500:
            raise TokenizerUnavailable(f"status={r.status_code}")
        if r.status_code != 200:
            body = _parse_error(r)
            raise TokenizerError(body["error_type"], body["message"], r.status_code)
        return str(r.json()["token"])

    async def detokenize(self, request_uuid: str, token: str) -> tuple[str, str]:
        """Returns (plaintext, type)."""
        try:
            r = await self._client.post(
                "/v1/detokenize",
                json={"request_uuid": request_uuid, "token": token},
            )
        except httpx.HTTPError as exc:
            raise TokenizerUnavailable(str(exc)) from exc
        if r.status_code >= 500:
            raise TokenizerUnavailable(f"status={r.status_code}")
        if r.status_code != 200:
            body = _parse_error(r)
            DETOKENIZE_FAILURES_TOTAL.labels(reason=body["error_type"]).inc()
            raise TokenizerError(body["error_type"], body["message"], r.status_code)
        data = r.json()
        return str(data["plaintext"]), str(data["type"])

    async def release_request(self, request_uuid: str) -> None:
        try:
            r = await self._client.post(
                "/v1/release_request",
                json={"request_uuid": request_uuid},
            )
        except httpx.HTTPError as exc:
            raise TokenizerUnavailable(str(exc)) from exc
        if r.status_code not in (204, 200, 404):
            body = _parse_error(r)
            raise TokenizerError(body["error_type"], body["message"], r.status_code)


def _parse_error(r: httpx.Response) -> dict[str, Any]:
    try:
        data = r.json()
        return {
            "error_type": str(data.get("error_type", "UNKNOWN")),
            "message": str(data.get("message", "")),
        }
    except Exception:
        return {"error_type": "UNKNOWN", "message": r.text[:200]}
