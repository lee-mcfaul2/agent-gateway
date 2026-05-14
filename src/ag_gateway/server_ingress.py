from __future__ import annotations

import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from ag_gateway.config import Config
from ag_gateway.hooks.audit import AuditEvent, AuditLogger
from ag_gateway.hooks.auth_oidc import JWTValidationError, OIDCValidator
from ag_gateway.hooks.cost_cap import CostCap, CostCapExceeded, CostMeter
from ag_gateway.hooks.llm_guard import LLMGuardClient, LLMGuardUnavailable
from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.scrub_inbound import scrub_inbound
from ag_gateway.hooks.tokenizer_client import TokenizerClient, TokenizerUnavailable
from ag_gateway.jobs.launcher import (
    AgentFailedError,
    AgentJobLauncher,
    AgentLaunchError,
    AgentTimeoutError,
)
from ag_gateway.jobs.result import (
    FinishReason,
    TerminateInvalid,
    extract_terminate,
)
from ag_gateway.mcp_proxy.request_state import RequestContext, RequestStateStore
from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import (
    REQUEST_DURATION,
    REQUESTS_TOTAL,
    SANDBOX_FINISH_REASON_TOTAL,
    SANDBOX_RESPONSE_SCHEMA_MISMATCH_TOTAL,
)
from ag_gateway.obs.quarantine import QuarantineRecord, QuarantineStore
from ag_gateway.prompts.bundle_view import BundleView
from ag_gateway.tools.catalog import compute_available_tools

log = get_logger(__name__)


@dataclass
class IngressDeps:
    oidc: OIDCValidator
    bundle: BundleView
    llm_guard: LLMGuardClient
    config: Config
    scrub_engine: ScrubEngine
    tokenizer: TokenizerClient
    state: RequestStateStore
    launcher: AgentJobLauncher
    audit: AuditLogger
    quarantine: QuarantineStore
    cost_meter: CostMeter
    litellm_internal_url: str
    gateway_mcp_internal_url: str


def _error(
    error_type: str, http_status: int, message: str, retriable: bool = False
) -> dict[str, Any]:
    return {
        "error_type": error_type,
        "retriable": retriable,
        "message": message,
    }


def make_router(deps: IngressDeps) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        authorization: str = Header(default=""),
        traceparent: str = Header(default=""),
    ) -> dict[str, Any]:
        start = time.time()
        body = await request.json()

        # 1. JWT validation
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=401,
                detail=_error("JWT_MISSING", 401, "missing Authorization"),
            )
        token = authorization.split(" ", 1)[1]
        try:
            user = deps.oidc.validate(token)
        except JWTValidationError as exc:
            raise HTTPException(
                status_code=401,
                detail=_error("JWT_VALIDATION_FAILED", 401, exc.message),
            ) from exc

        # 2. Validate body against bundled user-prompt.json
        validation_err = deps.bundle.user_prompt_validator.validate(body)
        if validation_err is not None:
            raise HTTPException(
                status_code=400,
                detail=_error("USER_PROMPT_INVALID", 400, validation_err),
            )

        prompt_uuid = body["prompt_uuid"]
        user_text = body["text"]
        requested_model = body.get("model")

        # 3. Cost cap (uses envelope_cost_caps from bundle)
        caps = deps.bundle.envelope_cost_caps
        try:
            deps.cost_meter.check(
                "user-prompt",
                user.sub,
                CostCap(max_usd=caps.max_cost_usd, window_seconds=3600),
            )
        except CostCapExceeded as exc:
            REQUESTS_TOTAL.labels(prompt="user-prompt", outcome="cost_cap").inc()
            raise HTTPException(
                status_code=429,
                detail=_error("COST_CAP_EXCEEDED", 429, str(exc)),
            ) from exc

        # 4. Mint request_uuid + init tokenizer
        request_uuid = str(_uuid.uuid4())
        ttl_seconds = caps.max_wallclock_ms // 1000 + 60
        try:
            await deps.tokenizer.init_request(request_uuid, ttl_seconds)
        except TokenizerUnavailable as exc:
            REQUESTS_TOTAL.labels(prompt="user-prompt", outcome="error").inc()
            raise HTTPException(
                status_code=503,
                detail=_error(
                    "TOKENIZER_UNAVAILABLE", 503, str(exc), retriable=True
                ),
            ) from exc

        # 5. LLM Guard inbound scan (fail-closed)
        try:
            inbound = await deps.llm_guard.scan_inbound(user_text, request_uuid)
        except LLMGuardUnavailable as exc:
            await deps.quarantine.write(
                QuarantineRecord(
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt_uuid,
                    reason="LLM_GUARD_UNAVAILABLE",
                    category="",
                    snapshot={},
                )
            )
            try:
                await deps.tokenizer.release_request(request_uuid)
            except Exception:
                pass
            raise HTTPException(
                status_code=503,
                detail=_error(
                    "LLM_GUARD_UNAVAILABLE", 503, str(exc), retriable=True
                ),
            ) from exc

        if inbound.action == "block":
            await deps.quarantine.write(
                QuarantineRecord(
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt_uuid,
                    reason="LLM_GUARD_BLOCK",
                    category=",".join(inbound.categories),
                    snapshot={"categories": inbound.categories},
                )
            )
            await deps.audit.log(
                AuditEvent(
                    event_type="llm_guard_block",
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt_uuid,
                    outcome="blocked",
                    payload={"categories": inbound.categories},
                )
            )
            try:
                await deps.tokenizer.release_request(request_uuid)
            except Exception:
                pass
            raise HTTPException(
                status_code=400,
                detail=_error(
                    "PROMPT_BLOCKED_BY_LLM_GUARD",
                    400,
                    ",".join(inbound.categories),
                ),
            )
        elif inbound.action == "flag":
            await deps.audit.log(
                AuditEvent(
                    event_type="llm_guard_flag",
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt_uuid,
                    outcome="flagged",
                    payload={"categories": inbound.categories},
                )
            )

        # 6. scrub_inbound — PII tokenization + secret detection
        try:
            scrub = await scrub_inbound(
                user_text, request_uuid, deps.scrub_engine, deps.tokenizer
            )
        except TokenizerUnavailable as exc:
            try:
                await deps.tokenizer.release_request(request_uuid)
            except Exception:
                pass
            raise HTTPException(
                status_code=503,
                detail=_error(
                    "TOKENIZER_UNAVAILABLE", 503, str(exc), retriable=True
                ),
            ) from exc

        for sec in scrub.secret_events:
            await deps.quarantine.write(
                QuarantineRecord(
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt_uuid,
                    reason="SECRET_EXFILTRATION",
                    category=sec.category,
                    snapshot={
                        "category": sec.category,
                        "text_with_redaction": sec.text_with_redaction,
                    },
                )
            )
            await deps.audit.log(
                AuditEvent(
                    event_type="secret_exfiltration",
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt_uuid,
                    outcome="redacted_and_quarantined",
                    payload={"category": sec.category},
                )
            )

        # 7. Compute AVAILABLE_TOOLS from JWT permissions
        available_tools = compute_available_tools(
            deps.bundle, frozenset(user.permissions)
        )

        # 8. Resolve model
        cfg = deps.config
        if requested_model:
            if requested_model not in cfg.allowed_models:
                try:
                    await deps.tokenizer.release_request(request_uuid)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=400,
                    detail=_error("MODEL_NOT_ALLOWED", 400, requested_model),
                )
            model = requested_model
        else:
            model = cfg.default_model

        # 9. Store RequestContext
        deps.state.put(
            request_uuid,
            RequestContext(
                user_claims=user,
                jwt=token,
                prompt_uuid=prompt_uuid,
                spiffe_id="",
                created_at=time.time(),
                available_tools=available_tools,
            ),
        )

        # 10. Launch sandbox Job + handle result
        try:
            try:
                job_res = await deps.launcher.launch_and_wait(
                    request_uuid=request_uuid,
                    prompt_uuid=prompt_uuid,
                    litellm_url=deps.litellm_internal_url,
                    gateway_mcp_url=deps.gateway_mcp_internal_url,
                    tokenized_user_input=scrub.scrubbed_text,
                    available_tools=available_tools,
                    model=model,
                    max_iterations=caps.max_iterations,
                    wallclock_timeout_seconds=caps.max_wallclock_ms // 1000,
                    traceparent=traceparent,
                )
            except AgentLaunchError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=_error(
                        "AGENT_LAUNCH_FAILED", 503, str(exc), retriable=True
                    ),
                ) from exc
            except AgentTimeoutError as exc:
                raise HTTPException(
                    status_code=504,
                    detail=_error("AGENT_TIMEOUT", 504, str(exc), retriable=True),
                ) from exc
            except AgentFailedError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=_error(
                        "AGENT_FAILED", 500, str(exc), retriable=True
                    ),
                ) from exc

            # 11. Parse terminate envelope
            try:
                terminate = extract_terminate(deps.bundle, job_res.terminate_body)
            except TerminateInvalid as exc:
                raise HTTPException(
                    status_code=500,
                    detail=_error("AGENT_FAILED", 500, f"bad terminate: {exc}"),
                ) from exc

            SANDBOX_FINISH_REASON_TOTAL.labels(reason=terminate.finish_reason.value).inc()

            # 12. Non-terminate finish reasons
            if terminate.finish_reason == FinishReason.SCHEMA_MISMATCH:
                if terminate.error and terminate.error.mcp:
                    SANDBOX_RESPONSE_SCHEMA_MISMATCH_TOTAL.labels(
                        mcp=terminate.error.mcp, tool=terminate.error.tool
                    ).inc()
                await deps.quarantine.write(
                    QuarantineRecord(
                        request_uuid=request_uuid,
                        user_sub=user.sub,
                        prompt_uuid=prompt_uuid,
                        reason="SCHEMA_MISMATCH",
                        category=terminate.error.category if terminate.error else "",
                        snapshot={
                            "error": terminate.error.__dict__ if terminate.error else {}
                        },
                    )
                )
                raise HTTPException(
                    status_code=500,
                    detail=_error(
                        "SANDBOX_SCHEMA_MISMATCH",
                        500,
                        "agent aborted on schema mismatch",
                    ),
                )
            if terminate.finish_reason == FinishReason.LLM_ERROR:
                raise HTTPException(
                    status_code=502,
                    detail=_error(
                        "LITELLM_UPSTREAM_ERROR", 502, "LLM call failed in sandbox"
                    ),
                )
            if terminate.finish_reason == FinishReason.INTERNAL_ERROR:
                raise HTTPException(
                    status_code=500,
                    detail=_error(
                        "SANDBOX_INTERNAL_ERROR", 500, "sandbox internal error"
                    ),
                )

            if terminate.finish_reason == FinishReason.ITERATION_CAP:
                final_text = terminate.response or "(agent reached iteration cap)"
            elif terminate.finish_reason == FinishReason.WALLCLOCK_TIMEOUT:
                final_text = terminate.response or "(agent reached wallclock timeout)"
            else:
                final_text = terminate.response or ""

            # 13. Detokenize response
            final = await _detokenize_response(
                final_text, request_uuid, deps.tokenizer
            )

            REQUESTS_TOTAL.labels(
                prompt="user-prompt", outcome=terminate.finish_reason.value
            ).inc()
            REQUEST_DURATION.labels(
                prompt="user-prompt", outcome=terminate.finish_reason.value
            ).observe(time.time() - start)
            await deps.audit.log(
                AuditEvent(
                    event_type="request",
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt_uuid,
                    outcome=terminate.finish_reason.value,
                    payload={
                        "tools_called": [
                            tc.__dict__ for tc in terminate.tools_called
                        ]
                    },
                )
            )

            return {
                "id": request_uuid,
                "object": "chat.completion",
                "created": int(start),
                "model": terminate.model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": final},
                    }
                ],
            }
        finally:
            try:
                await deps.tokenizer.release_request(request_uuid)
            finally:
                deps.state.drop(request_uuid)

    return router


async def _detokenize_response(
    text: str, request_uuid: str, tokenizer: TokenizerClient
) -> str:
    """Detokenize the terminate envelope's response string."""
    from ag_gateway.mcp_proxy.routes import _replace_tokens_in_string

    return await _replace_tokens_in_string(text, request_uuid, tokenizer)
