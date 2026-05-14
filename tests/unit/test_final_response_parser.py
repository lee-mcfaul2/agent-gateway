from __future__ import annotations

from pathlib import Path

import pytest

from ag_gateway.jobs.result import (
    ErrorBlock,
    FinishReason,
    TerminateInvalid,
    TerminateResult,
    TokensUsed,
    extract_terminate,
)
from ag_gateway.prompts.bundle_view import BundleView


FIXTURE_BUNDLE = Path(__file__).parent.parent / "fixtures" / "bundle-v1"


@pytest.fixture
def view():
    return BundleView.from_bundle(FIXTURE_BUNDLE)


def _valid_terminate():
    return {
        "terminate": {
            "request_uuid": "8d3c5a90-2a91-4f6e-9b73-1f4d6e5c2b10",
            "prompt_uuid": "c9e1f4b8-3d7a-4e25-9bcd-7e2a3f1d8b04",
            "response": "the answer",
            "iterations": 2,
            "tools_called": [{"mcp": "kb", "tool": "search", "outcome": "ok"}],
            "model": "claude-sonnet-4-6",
            "tokens_used": {"prompt": 100, "completion": 50, "total": 150},
            "finish_reason": "terminate",
        }
    }


def test_parse_happy_terminate(view):
    result = extract_terminate(view, _valid_terminate())
    assert isinstance(result, TerminateResult)
    assert result.finish_reason == FinishReason.TERMINATE
    assert result.response == "the answer"
    assert result.iterations == 2
    assert result.tokens_used == TokensUsed(prompt=100, completion=50, total=150)


def test_parse_iteration_cap(view):
    body = _valid_terminate()
    body["terminate"]["finish_reason"] = "iteration_cap"
    body["terminate"]["error"] = {"category": "FINISH_iteration_cap"}
    body["terminate"]["response"] = None
    result = extract_terminate(view, body)
    assert result.finish_reason == FinishReason.ITERATION_CAP
    assert result.error is not None
    assert result.error.category == "FINISH_iteration_cap"


def test_parse_schema_mismatch_includes_validation_errors(view):
    body = _valid_terminate()
    body["terminate"]["finish_reason"] = "schema_mismatch"
    body["terminate"]["response"] = None
    body["terminate"]["error"] = {
        "category": "SANDBOX_RESPONSE_SCHEMA_MISMATCH",
        "mcp": "kb",
        "tool": "search",
        "validation_errors": ["rows must be array"],
    }
    result = extract_terminate(view, body)
    assert result.finish_reason == FinishReason.SCHEMA_MISMATCH
    assert result.error.validation_errors == ["rows must be array"]


def test_reject_malformed_envelope(view):
    with pytest.raises(TerminateInvalid):
        extract_terminate(view, {"terminate": {"only_one_field": "x"}})


def test_reject_missing_terminate_key(view):
    with pytest.raises(TerminateInvalid):
        extract_terminate(view, {"not_terminate": {}})
