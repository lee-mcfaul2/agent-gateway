from __future__ import annotations

from ag_gateway.hooks.envelope import wrap_error, wrap_success


def test_wrap_success_shape() -> None:
    body = wrap_success({"rows": [1, 2]}, mcp="kb", tool="search", request_uuid="r")
    assert body["tool_result"]["ok"] is True
    assert body["tool_result"]["mcp"] == "kb"
    assert body["tool_result"]["data"] == {"rows": [1, 2]}


def test_wrap_error_shape() -> None:
    body = wrap_error("OPA_DENY", "missing_permission:audit:read", mcp="audit", tool="search", request_uuid="r")
    assert body["tool_result"]["ok"] is False
    assert body["tool_result"]["error"] == "OPA_DENY"
    assert "missing_permission" in body["tool_result"]["reason"]
