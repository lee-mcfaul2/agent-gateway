"""Parse the sandbox terminate envelope (final-response.json shape)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from ag_gateway.prompts.bundle_view import BundleView


class TerminateInvalid(Exception):
    pass


class FinishReason(enum.StrEnum):
    TERMINATE = "terminate"
    ITERATION_CAP = "iteration_cap"
    WALLCLOCK_TIMEOUT = "wallclock_timeout"
    SCHEMA_MISMATCH = "schema_mismatch"
    LLM_ERROR = "llm_error"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ToolCallSummary:
    mcp: str
    tool: str
    outcome: str


@dataclass(frozen=True)
class TokensUsed:
    prompt: int
    completion: int
    total: int


@dataclass(frozen=True)
class ErrorBlock:
    category: str
    mcp: str = ""
    tool: str = ""
    message: str = ""
    expected_schema_digest: str = ""
    validation_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TerminateResult:
    request_uuid: str
    prompt_uuid: str
    response: str | None
    iterations: int
    tools_called: list[ToolCallSummary]
    model: str
    tokens_used: TokensUsed | None
    finish_reason: FinishReason
    error: ErrorBlock | None


def extract_terminate(view: BundleView, raw: dict[str, Any]) -> TerminateResult:
    """Validate raw envelope against bundled final-response.json, return typed result."""
    err = view.final_response_validator.validate(raw)
    if err is not None:
        raise TerminateInvalid(f"final-response.json validation failed: {err}")
    body = raw.get("terminate")
    if body is None or not isinstance(body, dict):
        raise TerminateInvalid("missing terminate object")
    tokens = None
    if body.get("tokens_used"):
        t = body["tokens_used"]
        tokens = TokensUsed(
            prompt=int(t["prompt"]), completion=int(t["completion"]), total=int(t["total"])
        )
    err_block = None
    if body.get("error"):
        e = body["error"]
        err_block = ErrorBlock(
            category=str(e["category"]),
            mcp=str(e.get("mcp", "")),
            tool=str(e.get("tool", "")),
            message=str(e.get("message", "")),
            expected_schema_digest=str(e.get("expected_schema_digest", "")),
            validation_errors=list(e.get("validation_errors", [])),
        )
    return TerminateResult(
        request_uuid=str(body["request_uuid"]),
        prompt_uuid=str(body["prompt_uuid"]),
        response=body.get("response"),
        iterations=int(body["iterations"]),
        tools_called=[ToolCallSummary(**t) for t in body.get("tools_called", [])],
        model=str(body["model"]),
        tokens_used=tokens,
        finish_reason=FinishReason(body["finish_reason"]),
        error=err_block,
    )
