from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Header, Request

from ag_gateway.hooks.envelope import wrap_error, wrap_success
from ag_gateway.hooks.opa_authz import check as opa_check
from ag_gateway.hooks.opa_client import OPAClient
from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.scrub_outbound import scrub_outbound
from ag_gateway.hooks.tokenizer_client import TokenizerClient, TokenizerError, TokenizerUnavailable
from ag_gateway.mcp_proxy.client import CallFail, MCPClientPool
from ag_gateway.mcp_proxy.registry import MCPRegistry
from ag_gateway.mcp_proxy.request_state import RequestStateStore
from ag_gateway.obs.metrics import TOOL_CALLS_TOTAL, UUID_MISMATCH_TOTAL
from ag_gateway.schemas.validate import SchemaRegistry

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TOKEN_RE = re.compile(r"\bTOKEN_[A-Z_]+_[A-Z2-7]+\b")


class Deps:
    """Bundle of dependencies the route needs. Wired in server.py."""

    def __init__(
        self,
        state: RequestStateStore,
        mcps: MCPRegistry,
        mcp_pool: MCPClientPool,
        schemas: SchemaRegistry,
        tokenizer: TokenizerClient,
        opa: OPAClient,
        scrub_engine: ScrubEngine,
    ) -> None:
        self.state = state
        self.mcps = mcps
        self.mcp_pool = mcp_pool
        self.schemas = schemas
        self.tokenizer = tokenizer
        self.opa = opa
        self.scrub_engine = scrub_engine


def make_router(deps: Deps) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/mcp/{mcp}/{tool}")
    async def call_tool(
        mcp: str,
        tool: str,
        request: Request,
        x_spiffe_id: str = Header(default=""),
    ) -> dict[str, Any]:
        body = await request.json()
        request_uuid = str(body.get("request_uuid", ""))
        args = dict(body.get("args", {}))

        if not UUID_RE.match(request_uuid):
            UUID_MISMATCH_TOTAL.labels(reason="malformed").inc()
            return wrap_error(
                "UUID_MISMATCH", "malformed", mcp=mcp, tool=tool, request_uuid=request_uuid
            )

        ctx = deps.state.get(request_uuid)
        if ctx is None:
            UUID_MISMATCH_TOTAL.labels(reason="stale").inc()
            return wrap_error(
                "UUID_MISMATCH", "stale", mcp=mcp, tool=tool, request_uuid=request_uuid
            )
        if x_spiffe_id and ctx.spiffe_id != x_spiffe_id:
            UUID_MISMATCH_TOTAL.labels(reason="foreign_spiffe").inc()
            return wrap_error(
                "UUID_MISMATCH",
                "foreign_spiffe",
                mcp=mcp,
                tool=tool,
                request_uuid=request_uuid,
            )

        try:
            entry = deps.mcps.get(mcp)
        except KeyError:
            return wrap_error(
                "MCP_UNAVAILABLE", "not_in_catalog", mcp=mcp, tool=tool, request_uuid=request_uuid
            )

        decision = await opa_check(
            deps.opa, ctx.user_claims, mcp, tool, args, request_uuid
        )
        if not decision.allow:
            TOOL_CALLS_TOTAL.labels(mcp=mcp, tool=tool, outcome="opa_deny").inc()
            return wrap_error(
                "OPA_DENY", decision.reason, mcp=mcp, tool=tool, request_uuid=request_uuid
            )

        schema_ref = f"{mcp}/{entry.schema_version}/{tool}.request.json"
        err = deps.schemas.validate(args, schema_ref, kind="request", mcp=mcp)
        if err is not None:
            TOOL_CALLS_TOTAL.labels(mcp=mcp, tool=tool, outcome="schema_fail").inc()
            return wrap_error(
                "SCHEMA_VALIDATION_FAILED",
                err.reason,
                mcp=mcp,
                tool=tool,
                request_uuid=request_uuid,
            )

        try:
            args = await _detokenize_args(args, request_uuid, deps.tokenizer)
        except TokenizerUnavailable as exc:
            TOOL_CALLS_TOTAL.labels(mcp=mcp, tool=tool, outcome="mcp_error").inc()
            return wrap_error(
                "TOKENIZER_UNAVAILABLE",
                str(exc),
                mcp=mcp,
                tool=tool,
                request_uuid=request_uuid,
            )
        except TokenizerError as exc:
            return wrap_error(
                exc.error_type,
                exc.message,
                mcp=mcp,
                tool=tool,
                request_uuid=request_uuid,
            )

        client = deps.mcp_pool.for_(entry)
        res = await client.call(tool, args)
        if isinstance(res, CallFail):
            TOOL_CALLS_TOTAL.labels(mcp=mcp, tool=tool, outcome="mcp_error").inc()
            return wrap_error(res.error, res.reason, mcp=mcp, tool=tool, request_uuid=request_uuid)

        schema_ref = f"{mcp}/{entry.schema_version}/{tool}.response.json"
        err = deps.schemas.validate(res.body, schema_ref, kind="response", mcp=mcp)
        if err is not None:
            TOOL_CALLS_TOTAL.labels(mcp=mcp, tool=tool, outcome="schema_fail").inc()
            return wrap_error(
                "SCHEMA_VALIDATION_FAILED",
                err.reason,
                mcp=mcp,
                tool=tool,
                request_uuid=request_uuid,
            )

        scrubbed = await _scrub_response_recursive(
            res.body, request_uuid, deps.scrub_engine, deps.tokenizer
        )

        TOOL_CALLS_TOTAL.labels(mcp=mcp, tool=tool, outcome="ok").inc()
        return wrap_success(scrubbed, mcp=mcp, tool=tool, request_uuid=request_uuid)

    return router


async def _detokenize_args(
    args: dict[str, Any], request_uuid: str, tokenizer: TokenizerClient
) -> dict[str, Any]:
    """Walk the args; replace every TOKEN_* string with its plaintext via tokenizer.detokenize."""
    return await _walk_replace(args, request_uuid, tokenizer)


async def _walk_replace(
    obj: Any, request_uuid: str, tokenizer: TokenizerClient
) -> Any:
    if isinstance(obj, str):
        return await _replace_tokens_in_string(obj, request_uuid, tokenizer)
    if isinstance(obj, list):
        return [await _walk_replace(x, request_uuid, tokenizer) for x in obj]
    if isinstance(obj, dict):
        return {k: await _walk_replace(v, request_uuid, tokenizer) for k, v in obj.items()}
    return obj


async def _replace_tokens_in_string(
    s: str, request_uuid: str, tokenizer: TokenizerClient
) -> str:
    matches = list(TOKEN_RE.finditer(s))
    if not matches:
        return s
    parts: list[str] = []
    cursor = 0
    for m in matches:
        parts.append(s[cursor : m.start()])
        plaintext, _type = await tokenizer.detokenize(request_uuid, m.group(0))
        parts.append(plaintext)
        cursor = m.end()
    parts.append(s[cursor:])
    return "".join(parts)


async def _scrub_response_recursive(
    obj: Any, request_uuid: str, engine: ScrubEngine, tokenizer: TokenizerClient
) -> Any:
    if isinstance(obj, str):
        result = await scrub_outbound(obj, request_uuid, engine, tokenizer)
        return result.scrubbed_text
    if isinstance(obj, list):
        return [
            await _scrub_response_recursive(x, request_uuid, engine, tokenizer) for x in obj
        ]
    if isinstance(obj, dict):
        return {
            k: await _scrub_response_recursive(v, request_uuid, engine, tokenizer)
            for k, v in obj.items()
        }
    return obj
