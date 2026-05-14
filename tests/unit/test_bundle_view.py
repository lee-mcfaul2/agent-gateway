from __future__ import annotations

from pathlib import Path

import pytest

from ag_gateway.prompts.bundle_view import BundleView, ToolEntry

FIXTURE_BUNDLE = Path(__file__).parent.parent / "fixtures" / "bundle-v1"


def test_load_bundle_view():
    view = BundleView.from_bundle(FIXTURE_BUNDLE)
    assert view.digest.startswith("sha256:")
    assert view.envelope_cost_caps.max_iterations >= 1
    assert "kb" in view.services
    assert "customer" in view.services


def test_user_prompt_validator_compiles():
    view = BundleView.from_bundle(FIXTURE_BUNDLE)
    err = view.user_prompt_validator.validate({
        "schema_uuid": "8d3c5a90-2a91-4f6e-9b73-1f4d6e5c2b10",
        "prompt_uuid": "c9e1f4b8-3d7a-4e25-9bcd-7e2a3f1d8b04",
        "text": "hi",
    })
    assert err is None


def test_user_prompt_validator_rejects_missing_field():
    view = BundleView.from_bundle(FIXTURE_BUNDLE)
    err = view.user_prompt_validator.validate({
        "schema_uuid": "8d3c5a90-2a91-4f6e-9b73-1f4d6e5c2b10",
        "text": "hi",
    })
    assert err is not None


def test_services_dict_shape():
    view = BundleView.from_bundle(FIXTURE_BUNDLE)
    kb_tools = view.services["kb"]
    assert len(kb_tools) == 2
    names = sorted(t.name for t in kb_tools)
    assert names == ["fetch", "search"]
    for t in kb_tools:
        assert isinstance(t, ToolEntry)
        assert t.write is False
        assert "kb:read" in t.requires_permissions


def test_per_tool_request_validator():
    view = BundleView.from_bundle(FIXTURE_BUNDLE)
    kb_search = next(t for t in view.services["kb"] if t.name == "search")
    assert kb_search.request_validator.validate({"q": "hello"}) is None
    assert kb_search.request_validator.validate({}) is not None


def test_final_response_validator():
    view = BundleView.from_bundle(FIXTURE_BUNDLE)
    err = view.final_response_validator.validate({
        "terminate": {
            "request_uuid": "8d3c5a90-2a91-4f6e-9b73-1f4d6e5c2b10",
            "prompt_uuid": "c9e1f4b8-3d7a-4e25-9bcd-7e2a3f1d8b04",
            "response": "ok",
            "iterations": 1,
            "tools_called": [],
            "model": "x",
            "finish_reason": "terminate",
        }
    })
    assert err is None


def test_missing_bundle_raises():
    with pytest.raises(FileNotFoundError):
        BundleView.from_bundle(Path("/tmp/definitely-does-not-exist-xyz"))
