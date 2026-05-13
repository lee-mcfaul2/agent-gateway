from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ag_gateway.hooks.auth_oidc import UserClaims
from ag_gateway.prompts.registry import Prompt


@dataclass(frozen=True)
class RequestContext:
    user_claims: UserClaims
    prompt: Prompt
    spiffe_id: str
    created_at: float
    jwt: str


class RequestStateStore:
    """In-memory map of REQUEST_UUID -> RequestContext."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self._store: dict[str, RequestContext] = {}
        self._lock = threading.RLock()
        self._ttl = ttl_seconds

    def put(self, request_uuid: str, ctx: RequestContext) -> None:
        with self._lock:
            self._store[request_uuid] = ctx

    def get(self, request_uuid: str) -> RequestContext | None:
        with self._lock:
            ctx = self._store.get(request_uuid)
            if ctx is None:
                return None
            if time.time() - ctx.created_at > self._ttl:
                del self._store[request_uuid]
                return None
            return ctx

    def drop(self, request_uuid: str) -> None:
        with self._lock:
            self._store.pop(request_uuid, None)
