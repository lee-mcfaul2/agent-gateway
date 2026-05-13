from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient, PyJWKClientError
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
)

from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import JWT_FAILURES_TOTAL, JWT_JWKS_REFRESH_FAILURES_TOTAL


log = get_logger(__name__)


class JWTValidationError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class UserClaims:
    sub: str
    groups: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class OIDCValidator:
    """Validates OIDC JWTs against a configured issuer + audience.

    Caches JWKS; refreshes on a background interval.
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_uri: str | None = None,
        refresh_seconds: int = 3600,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._refresh_seconds = refresh_seconds
        self._jwks_uri = jwks_uri or self._discover_jwks(issuer)
        self._jwk_client = PyJWKClient(self._jwks_uri, cache_keys=True, lifespan=refresh_seconds)
        self._last_refresh: float = 0.0

    @staticmethod
    def _discover_jwks(issuer: str) -> str:
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        r = httpx.get(url, timeout=5.0)
        r.raise_for_status()
        return str(r.json()["jwks_uri"])

    def validate(self, token: str) -> UserClaims:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token).key
        except PyJWKClientError as exc:
            JWT_JWKS_REFRESH_FAILURES_TOTAL.labels(reason="signing_key").inc()
            raise JWTValidationError("signature", f"signing key not found: {exc}") from exc

        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "ES256"],
                audience=self._audience,
                issuer=self._issuer,
            )
        except ExpiredSignatureError as exc:
            JWT_FAILURES_TOTAL.labels(reason="expired").inc()
            raise JWTValidationError("expired", str(exc)) from exc
        except InvalidAudienceError as exc:
            JWT_FAILURES_TOTAL.labels(reason="audience").inc()
            raise JWTValidationError("audience", str(exc)) from exc
        except InvalidIssuerError as exc:
            JWT_FAILURES_TOTAL.labels(reason="issuer").inc()
            raise JWTValidationError("issuer", str(exc)) from exc
        except InvalidSignatureError as exc:
            JWT_FAILURES_TOTAL.labels(reason="signature").inc()
            raise JWTValidationError("signature", str(exc)) from exc
        except InvalidTokenError as exc:
            JWT_FAILURES_TOTAL.labels(reason="format").inc()
            raise JWTValidationError("format", str(exc)) from exc

        sub = claims.get("sub")
        if not sub:
            JWT_FAILURES_TOTAL.labels(reason="missing_claim").inc()
            raise JWTValidationError("missing_claim", "sub claim missing")

        return UserClaims(
            sub=str(sub),
            groups=tuple(claims.get("groups", [])),
            permissions=tuple(claims.get("permissions", [])),
            raw=dict(claims),
        )

    async def refresh_loop(self) -> None:
        """Background task: re-fetch JWKS periodically."""
        while True:
            await asyncio.sleep(self._refresh_seconds)
            try:
                self._jwk_client.fetch_data()
                self._last_refresh = time.time()
                log.debug("oidc.jwks_refreshed")
            except Exception as exc:
                JWT_JWKS_REFRESH_FAILURES_TOTAL.labels(reason="network").inc()
                log.warning("oidc.jwks_refresh_failed", err=str(exc))
