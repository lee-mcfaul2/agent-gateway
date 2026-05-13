from __future__ import annotations

import pytest
import respx
from httpx import Response

from ag_gateway.hooks.auth_oidc import UserClaims
from ag_gateway.hooks.opa_authz import build_input, check
from ag_gateway.hooks.opa_client import OPAClient


@pytest.fixture
async def opa() -> OPAClient:
    c = OPAClient("http://opa:8181")
    yield c
    await c.aclose()


def test_build_input_shape() -> None:
    u = UserClaims(sub="alice", groups=("support",), permissions=("kb:read",))
    doc = build_input(u, "kb", "search", {"q": "x"}, "req-1")
    assert doc["user"]["sub"] == "alice"
    assert doc["mcp"] == "kb"
    assert doc["tool"] == "search"
    assert doc["args"] == {"q": "x"}
    assert doc["request_uuid"] == "req-1"


@respx.mock
async def test_check_allow(opa: OPAClient) -> None:
    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        return_value=Response(200, json={"result": {"allow": True, "reason": "ok"}})
    )
    u = UserClaims(sub="a", permissions=("kb:read",))
    d = await check(opa, u, "kb", "search", {}, "r")
    assert d.allow is True


@respx.mock
async def test_check_deny_increments_metric(opa: OPAClient) -> None:
    respx.post("http://opa:8181/v1/data/ag_gateway/authz/decision").mock(
        return_value=Response(
            200,
            json={"result": {"allow": False, "reason": "missing_permission:audit:read"}},
        )
    )
    u = UserClaims(sub="a")
    d = await check(opa, u, "audit_db", "search", {}, "r")
    assert d.allow is False
    assert d.reason.startswith("missing_permission")
    from ag_gateway.obs.metrics import OPA_DENIALS_TOTAL

    assert (
        OPA_DENIALS_TOTAL.labels(mcp="audit_db", tool="search", reason="missing_permission")._value.get() >= 1.0
    )
