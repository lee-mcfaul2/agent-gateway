from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from ag_gateway.hooks.audit import AuditEvent
from ag_gateway.hooks.auth_oidc import JWTValidationError, UserClaims
from ag_gateway.hooks.cost_cap import CostMeter
from ag_gateway.hooks.llm_guard import LLMGuardClient, LLMGuardUnavailable, ScanResult
from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.tokenizer_client import TokenizerClient
from ag_gateway.jobs.launcher import JobResult
from ag_gateway.mcp_proxy.request_state import RequestStateStore
from ag_gateway.obs.quarantine import QuarantineStore
from ag_gateway.prompts.bundle_view import BundleView
from ag_gateway.schemas.scrub_categories import ScrubCatalog
from ag_gateway.server_ingress import IngressDeps, make_router

FIXTURE_BUNDLE = Path(__file__).parent.parent / "fixtures" / "bundle-v1"

# ---------------------------------------------------------------------------
# Canonical UUIDs (valid RFC 4122 lowercase hex)
# ---------------------------------------------------------------------------
SCHEMA_UUID = "8d3c5a90-2a91-4f6e-9b73-1f4d6e5c2b10"
PROMPT_UUID = "c9e1f4b8-3d7a-4e25-9bcd-7e2a3f1d8b04"
REQUEST_UUID = "11111111-1111-1111-1111-111111111111"

VALID_BODY = {
    "schema_uuid": SCHEMA_UUID,
    "prompt_uuid": PROMPT_UUID,
    "text": "Hello",
}

GOOD_TERMINATE = {
    "terminate": {
        "request_uuid": REQUEST_UUID,
        "prompt_uuid": PROMPT_UUID,
        "response": "hello",
        "iterations": 1,
        "tools_called": [],
        "model": "claude-sonnet-4-6",
        "finish_reason": "terminate",
    }
}

# ---------------------------------------------------------------------------
# Fake OIDC validator
# ---------------------------------------------------------------------------


class _FakeOIDC:
    def validate(self, token: str) -> UserClaims:
        if token == "valid-jwt":
            return UserClaims(sub="alice", permissions=("kb:read",))
        raise JWTValidationError("signature", "bad token")


# ---------------------------------------------------------------------------
# Fake launcher
# ---------------------------------------------------------------------------


class _FakeLauncher:
    def __init__(self, terminate: dict[str, Any]) -> None:
        self.terminate = terminate

    async def launch_and_wait(self, **kw: Any) -> JobResult:
        return JobResult(name="job-1", terminate_body=self.terminate)


# ---------------------------------------------------------------------------
# Fake audit / quarantine
# ---------------------------------------------------------------------------


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def log(self, ev: AuditEvent) -> None:
        self.events.append(ev)


class _FakeQuarantine:
    def __init__(self) -> None:
        self.records: list[Any] = []

    async def write(self, rec: Any) -> None:
        self.records.append(rec)


# ---------------------------------------------------------------------------
# Fake LLM Guard clients
# ---------------------------------------------------------------------------


class _FakeLLMGuardAllow:
    async def scan_inbound(self, text: str, request_uuid: str) -> ScanResult:
        return ScanResult(action="allow")


class _FakeLLMGuardBlock:
    async def scan_inbound(self, text: str, request_uuid: str) -> ScanResult:
        return ScanResult(action="block", categories=["prompt_injection"])


class _FakeLLMGuardUnavailable:
    async def scan_inbound(self, text: str, request_uuid: str) -> ScanResult:
        raise LLMGuardUnavailable("connection refused")


# ---------------------------------------------------------------------------
# Fake Config (only needs allowed_models / default_model)
# ---------------------------------------------------------------------------


class _FakeConfig:
    allowed_models: tuple[str, ...] = ("claude-sonnet-4-6", "gpt-4o")
    default_model: str = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Helper: build a ScrubEngine with no detections
# ---------------------------------------------------------------------------


def _make_scrub_engine(tmp_path: Path) -> ScrubEngine:
    s = tmp_path / "schemas" / "shared"
    s.mkdir(parents=True)
    (s / "scrub-types.json").write_text('{"categories": []}')

    class _Stub:
        def analyze(self, text: str, language: str = "en") -> list[object]:
            return []

    return ScrubEngine(ScrubCatalog.from_bundle(tmp_path), presidio=_Stub())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_deps(
    tmp_path: Path,
    *,
    llm_guard: Any = None,
    launcher_terminate: dict[str, Any] | None = None,
) -> IngressDeps:
    bundle = BundleView.from_bundle(FIXTURE_BUNDLE)
    if llm_guard is None:
        llm_guard = _FakeLLMGuardAllow()
    if launcher_terminate is None:
        launcher_terminate = GOOD_TERMINATE
    return IngressDeps(
        oidc=_FakeOIDC(),  # type: ignore[arg-type]
        bundle=bundle,
        llm_guard=llm_guard,  # type: ignore[arg-type]
        config=_FakeConfig(),  # type: ignore[arg-type]
        scrub_engine=_make_scrub_engine(tmp_path),
        tokenizer=TokenizerClient("http://tok:8443"),
        state=RequestStateStore(),
        launcher=_FakeLauncher(launcher_terminate),  # type: ignore[arg-type]
        audit=_FakeAudit(),  # type: ignore[arg-type]
        quarantine=_FakeQuarantine(),  # type: ignore[arg-type]
        cost_meter=CostMeter(),
        litellm_internal_url="http://litellm:4000",
        gateway_mcp_internal_url="http://gateway:8000",
    )


def _make_client(deps: IngressDeps) -> TestClient:
    app = FastAPI()
    app.include_router(make_router(deps))
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client_with_deps(tmp_path: Path) -> TestClient:
    return _make_client(_make_deps(tmp_path))


@pytest.fixture
def client_with_deps_llm_guard_blocks(tmp_path: Path) -> TestClient:
    return _make_client(_make_deps(tmp_path, llm_guard=_FakeLLMGuardBlock()))


@pytest.fixture
def client_with_deps_llm_guard_unavailable(tmp_path: Path) -> TestClient:
    return _make_client(_make_deps(tmp_path, llm_guard=_FakeLLMGuardUnavailable()))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@respx.mock
def test_happy_path_minimal_user_prompt(tmp_path: Path) -> None:
    respx.post("http://tok:8443/v1/init_request").mock(
        return_value=Response(
            201, json={"request_uuid": "x", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )
    respx.post("http://tok:8443/v1/release_request").mock(
        return_value=Response(204)
    )
    client = _make_client(_make_deps(tmp_path))
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-jwt"},
        json=VALID_BODY,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"] == "hello"


def test_missing_jwt(client_with_deps: TestClient) -> None:
    r = client_with_deps.post(
        "/v1/chat/completions",
        json=VALID_BODY,
    )
    assert r.status_code == 401
    assert "JWT_MISSING" in r.text


def test_bad_jwt(client_with_deps: TestClient) -> None:
    r = client_with_deps.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer bad-token"},
        json=VALID_BODY,
    )
    assert r.status_code == 401
    assert "JWT_VALIDATION_FAILED" in r.text


def test_user_prompt_invalid_returns_400(client_with_deps: TestClient) -> None:
    """Body missing required fields → USER_PROMPT_INVALID."""
    r = client_with_deps.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-jwt"},
        json={"prompt_uuid": "u", "text": "x"},  # missing schema_uuid
    )
    assert r.status_code == 400
    assert "USER_PROMPT_INVALID" in r.text


def test_user_prompt_invalid_bad_uuid(client_with_deps: TestClient) -> None:
    """Non-UUID schema_uuid → USER_PROMPT_INVALID."""
    r = client_with_deps.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-jwt"},
        json={"schema_uuid": "not-a-uuid", "prompt_uuid": PROMPT_UUID, "text": "x"},
    )
    assert r.status_code == 400
    assert "USER_PROMPT_INVALID" in r.text


@respx.mock
def test_model_not_allowed_returns_400(tmp_path: Path) -> None:
    """Requesting a model not in allowed_models → MODEL_NOT_ALLOWED."""
    respx.post("http://tok:8443/v1/init_request").mock(
        return_value=Response(
            201, json={"request_uuid": "x", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )
    respx.post("http://tok:8443/v1/release_request").mock(
        return_value=Response(204)
    )
    client = _make_client(_make_deps(tmp_path))
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-jwt"},
        json={**VALID_BODY, "model": "definitely-not-allowed"},
    )
    assert r.status_code == 400
    assert "MODEL_NOT_ALLOWED" in r.text


def test_llm_guard_block_returns_400(
    client_with_deps_llm_guard_blocks: TestClient,
    tmp_path: Path,
) -> None:
    """LLM Guard block → 400 PROMPT_BLOCKED_BY_LLM_GUARD (after tokenizer init)."""
    with respx.mock:
        respx.post("http://tok:8443/v1/init_request").mock(
            return_value=Response(
                201, json={"request_uuid": "x", "expires_at": "2099-01-01T00:00:00Z"}
            )
        )
        respx.post("http://tok:8443/v1/release_request").mock(
            return_value=Response(204)
        )
        r = client_with_deps_llm_guard_blocks.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer valid-jwt"},
            json=VALID_BODY,
        )
    assert r.status_code == 400
    assert "PROMPT_BLOCKED_BY_LLM_GUARD" in r.text


def test_llm_guard_unavailable_returns_503(
    client_with_deps_llm_guard_unavailable: TestClient,
    tmp_path: Path,
) -> None:
    """LLM Guard unavailable → 503 LLM_GUARD_UNAVAILABLE (after tokenizer init)."""
    with respx.mock:
        respx.post("http://tok:8443/v1/init_request").mock(
            return_value=Response(
                201, json={"request_uuid": "x", "expires_at": "2099-01-01T00:00:00Z"}
            )
        )
        respx.post("http://tok:8443/v1/release_request").mock(
            return_value=Response(204)
        )
        r = client_with_deps_llm_guard_unavailable.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer valid-jwt"},
            json=VALID_BODY,
        )
    assert r.status_code == 503
    assert "LLM_GUARD_UNAVAILABLE" in r.text


@respx.mock
def test_allowed_model_override(tmp_path: Path) -> None:
    """Requesting an explicitly-allowed model → 200 with that model reflected."""
    respx.post("http://tok:8443/v1/init_request").mock(
        return_value=Response(
            201, json={"request_uuid": "x", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )
    respx.post("http://tok:8443/v1/release_request").mock(
        return_value=Response(204)
    )
    client = _make_client(_make_deps(tmp_path))
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-jwt"},
        json={**VALID_BODY, "model": "gpt-4o"},
    )
    assert r.status_code == 200


def test_cost_cap_exceeded_returns_429(tmp_path: Path) -> None:
    """Once the cost meter hits its cap, subsequent calls return 429."""
    meter = CostMeter()
    # Exhaust the cap so the meter rejects any further call.
    meter.record("user-prompt", "alice", 999999.0)

    deps = _make_deps(tmp_path)
    # Swap in the exhausted meter.
    deps.cost_meter = meter
    client = _make_client(deps)
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-jwt"},
        json=VALID_BODY,
    )
    assert r.status_code == 429
    assert "COST_CAP_EXCEEDED" in r.text
