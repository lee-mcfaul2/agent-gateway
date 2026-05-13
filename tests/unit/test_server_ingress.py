from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from ag_gateway.hooks.audit import AuditEvent
from ag_gateway.hooks.auth_oidc import UserClaims
from ag_gateway.hooks.cost_cap import CostMeter
from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.tokenizer_client import TokenizerClient
from ag_gateway.jobs.launcher import JobResult
from ag_gateway.mcp_proxy.request_state import RequestStateStore
from ag_gateway.prompts.registry import PromptRegistry
from ag_gateway.schemas.scrub_categories import ScrubCatalog
from ag_gateway.server_ingress import IngressDeps, make_router


class _FakeOIDC:
    def validate(self, token: str) -> UserClaims:
        if token == "good":
            return UserClaims(sub="alice", permissions=("kb:read",))
        from ag_gateway.hooks.auth_oidc import JWTValidationError

        raise JWTValidationError("signature", "bad")


class _FakeLauncher:
    def __init__(self, terminate: dict[str, Any]) -> None:
        self.terminate = terminate

    async def launch_and_wait(self, **kw: Any) -> JobResult:
        return JobResult(name="job-1", terminate_body=self.terminate)


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def log(self, ev: AuditEvent) -> None:
        self.events.append(ev)


class _FakeQuarantine:
    def __init__(self) -> None:
        self.records: list[Any] = []

    async def write(self, rec: Any) -> int:
        self.records.append(rec)
        return len(self.records)


@pytest.fixture
def deps(tmp_path: Path) -> IngressDeps:
    p = tmp_path / "prompts"
    p.mkdir()
    (p / "support.json").write_text(
        json.dumps(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "support_chat_v1",
                "allowed_responses": {},
                "cost_caps": {"max_usd": 1.0, "ttl_seconds": 60},
            }
        )
    )
    prompts = PromptRegistry.from_bundle(tmp_path)

    s = tmp_path / "schemas" / "shared"
    s.mkdir(parents=True)
    (s / "scrub-types.json").write_text(json.dumps({"categories": []}))

    class _Stub:
        def analyze(self, text: str, language: str = "en") -> list[object]:
            return []

    engine = ScrubEngine(ScrubCatalog.from_bundle(tmp_path), presidio=_Stub())  # type: ignore[arg-type]

    return IngressDeps(
        oidc=_FakeOIDC(),  # type: ignore[arg-type]
        prompts=prompts,
        scrub_engine=engine,
        tokenizer=TokenizerClient("http://tok:8443"),
        state=RequestStateStore(),
        launcher=_FakeLauncher({"terminate": {"answer": "hi"}}),  # type: ignore[arg-type]
        audit=_FakeAudit(),  # type: ignore[arg-type]
        quarantine=_FakeQuarantine(),  # type: ignore[arg-type]
        cost_meter=CostMeter(),
        litellm_internal_url="http://localhost:8000",
    )


@respx.mock
def test_happy_path(deps: IngressDeps) -> None:
    respx.post("http://tok:8443/v1/init_request").mock(
        return_value=Response(201, json={"request_uuid": "x", "expires_at": "2099-01-01T00:00:00Z"})
    )
    respx.post("http://tok:8443/v1/release_request").mock(return_value=Response(204))
    app = FastAPI()
    app.include_router(make_router(deps))
    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer good"},
        json={"model": "support_chat_v1", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["role"] == "assistant"


def test_missing_jwt(deps: IngressDeps) -> None:
    app = FastAPI()
    app.include_router(make_router(deps))
    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={"model": "support_chat_v1", "messages": []},
    )
    assert r.status_code == 401


def test_bad_jwt(deps: IngressDeps) -> None:
    app = FastAPI()
    app.include_router(make_router(deps))
    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer bad"},
        json={"model": "support_chat_v1", "messages": []},
    )
    assert r.status_code == 401


def test_unknown_prompt(deps: IngressDeps) -> None:
    app = FastAPI()
    app.include_router(make_router(deps))
    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer good"},
        json={"model": "nope", "messages": []},
    )
    assert r.status_code == 404
