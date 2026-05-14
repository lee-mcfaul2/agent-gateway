from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from ag_gateway.hooks.auth_oidc import UserClaims
from ag_gateway.hooks.opa_client import OPAClient
from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.tokenizer_client import TokenizerClient
from ag_gateway.mcp_proxy.client import MCPClientPool
from ag_gateway.mcp_proxy.registry import MCPRegistry
from ag_gateway.mcp_proxy.request_state import RequestContext, RequestStateStore
from ag_gateway.mcp_proxy.routes import Deps, make_router
from ag_gateway.prompts.bundle_view import BundleView
from ag_gateway.schemas.scrub_categories import ScrubCatalog
from ag_gateway.schemas.validate import SchemaRegistry

FIXTURE_BUNDLE = Path(__file__).parent.parent / "fixtures" / "bundle-v1"


@pytest.fixture
def fixtures(tmp_path: Path) -> dict[str, Any]:
    mcp_dir = tmp_path / "mcps"
    mcp_dir.mkdir()
    (mcp_dir / "catalog.json").write_text(
        json.dumps(
            {
                "mcps": [
                    {
                        "name": "kb",
                        "spiffe": "spiffe://x/kb",
                        "schema_version": "v1",
                        "schema_digest": "sha256:abc",
                    }
                ]
            }
        )
    )
    mcps = MCPRegistry.from_bundle(tmp_path)

    schemas_dir = tmp_path / "schemas" / "kb" / "v1"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "search.request.json").write_text(
        json.dumps({"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]})
    )
    (schemas_dir / "search.response.json").write_text(
        json.dumps({"type": "object"})
    )
    schemas = SchemaRegistry(tmp_path)

    shared_dir = tmp_path / "schemas" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "scrub-types.json").write_text(json.dumps({"categories": []}))

    class _Stub:
        def analyze(self, text: str, language: str = "en") -> list[object]:
            return []

    engine = ScrubEngine(ScrubCatalog.from_bundle(tmp_path), presidio=_Stub())  # type: ignore[arg-type]

    state = RequestStateStore()
    state.put(
        "11111111-1111-1111-1111-111111111111",
        RequestContext(
            user_claims=UserClaims(sub="alice", permissions=("kb:read",)),
            prompt_uuid="22222222-2222-2222-2222-222222222222",
            spiffe_id="spiffe://x/job-1",
            created_at=__import__("time").time(),
            jwt="test.jwt.token",
            available_tools=["kb.search"],
        ),
    )

    return {
        "state": state,
        "mcps": mcps,
        "schemas": schemas,
        "engine": engine,
    }


@respx.mock
def test_happy_path(fixtures: dict[str, Any]) -> None:
    tokenizer = TokenizerClient("http://tok:8443")
    opa = OPAClient("http://opa:8181")
    pool = MCPClientPool()

    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        return_value=Response(200, json={"result": {"allow": True, "reason": "ok"}})
    )
    mcp_route = respx.post(
        "http://kb-mcp.mcp.svc.cluster.local:8443/v1/tools/search"
    ).mock(return_value=Response(200, json={"rows": ["a", "b"]}))

    deps = Deps(
        state=fixtures["state"],
        mcps=fixtures["mcps"],
        mcp_pool=pool,
        schemas=fixtures["schemas"],
        tokenizer=tokenizer,
        opa=opa,
        scrub_engine=fixtures["engine"],
        bundle=BundleView.from_bundle(FIXTURE_BUNDLE),
        llm_guard=MagicMock(),
    )
    app = FastAPI()
    app.include_router(make_router(deps))
    client = TestClient(app)

    r = client.post(
        "/v1/mcp/kb/search",
        json={"request_uuid": "11111111-1111-1111-1111-111111111111", "args": {"q": "x"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tool_result"]["ok"] is True
    assert body["tool_result"]["data"]["rows"] == ["a", "b"]
    assert mcp_route.calls.last.request.headers["authorization"] == "Bearer test.jwt.token"


def test_uuid_mismatch_stale(fixtures: dict[str, Any]) -> None:
    deps = Deps(
        state=fixtures["state"],
        mcps=fixtures["mcps"],
        mcp_pool=MCPClientPool(),
        schemas=fixtures["schemas"],
        tokenizer=TokenizerClient("http://tok:8443"),
        opa=OPAClient("http://opa:8181"),
        scrub_engine=fixtures["engine"],
        bundle=BundleView.from_bundle(FIXTURE_BUNDLE),
        llm_guard=MagicMock(),
    )
    app = FastAPI()
    app.include_router(make_router(deps))
    client = TestClient(app)

    r = client.post(
        "/v1/mcp/kb/search",
        json={"request_uuid": "ffffffff-ffff-ffff-ffff-ffffffffffff", "args": {"q": "x"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tool_result"]["ok"] is False
    assert body["tool_result"]["error"] == "UUID_MISMATCH"
    assert body["tool_result"]["reason"] == "stale"


@respx.mock
def test_opa_deny(fixtures: dict[str, Any]) -> None:
    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(  # noqa: E501
        return_value=Response(
            200, json={"result": {"allow": False, "reason": "missing_permission:audit:read"}}
        )
    )
    deps = Deps(
        state=fixtures["state"],
        mcps=fixtures["mcps"],
        mcp_pool=MCPClientPool(),
        schemas=fixtures["schemas"],
        tokenizer=TokenizerClient("http://tok:8443"),
        opa=OPAClient("http://opa:8181"),
        scrub_engine=fixtures["engine"],
        bundle=BundleView.from_bundle(FIXTURE_BUNDLE),
        llm_guard=MagicMock(),
    )
    app = FastAPI()
    app.include_router(make_router(deps))
    client = TestClient(app)

    r = client.post(
        "/v1/mcp/kb/search",
        json={"request_uuid": "11111111-1111-1111-1111-111111111111", "args": {"q": "x"}},
    )
    body = r.json()
    assert body["tool_result"]["ok"] is False
    assert body["tool_result"]["error"] == "OPA_DENY"
