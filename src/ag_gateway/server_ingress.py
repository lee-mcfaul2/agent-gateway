from __future__ import annotations

import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from ag_gateway.hooks.audit import AuditEvent, AuditLogger
from ag_gateway.hooks.auth_oidc import JWTValidationError, OIDCValidator
from ag_gateway.hooks.cost_cap import CostCap, CostCapExceeded, CostMeter
from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.scrub_inbound import scrub_inbound
from ag_gateway.hooks.tokenizer_client import TokenizerClient, TokenizerUnavailable
from ag_gateway.jobs.launcher import (
    AgentFailedError,
    AgentJobLauncher,
    AgentLaunchError,
    AgentTimeoutError,
)
from ag_gateway.jobs.result import TerminateInvalid, extract_terminate
from ag_gateway.mcp_proxy.request_state import RequestContext, RequestStateStore
from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import REQUEST_DURATION, REQUESTS_TOTAL
from ag_gateway.obs.quarantine import QuarantineRecord, QuarantineStore
from ag_gateway.prompts.registry import PromptNotFound, PromptRegistry

log = get_logger(__name__)


@dataclass
class IngressDeps:
    oidc: OIDCValidator
    prompts: PromptRegistry
    scrub_engine: ScrubEngine
    tokenizer: TokenizerClient
    state: RequestStateStore
    launcher: AgentJobLauncher
    audit: AuditLogger
    quarantine: QuarantineStore
    cost_meter: CostMeter
    litellm_internal_url: str


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
    ) -> dict[str, Any]:
        start = time.time()
        body = await request.json()

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

        prompt_name = str(body.get("model", ""))
        try:
            prompt = deps.prompts.by_name(prompt_name)
        except PromptNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail=_error("PROMPT_NOT_FOUND", 404, prompt_name),
            ) from exc

        cap_usd = float(prompt.cost_caps.get("max_usd", 5.0))
        cap_window = int(prompt.cost_caps.get("window_seconds", 3600))
        try:
            deps.cost_meter.check(
                prompt.name,
                user.sub,
                CostCap(max_usd=cap_usd, window_seconds=cap_window),
            )
        except CostCapExceeded as exc:
            REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="cost_cap").inc()
            raise HTTPException(
                status_code=429, detail=_error("COST_CAP_EXCEEDED", 429, str(exc))
            ) from exc

        request_uuid = str(_uuid.uuid4())
        ttl_seconds = int(prompt.cost_caps.get("ttl_seconds", 600))
        try:
            await deps.tokenizer.init_request(request_uuid, ttl_seconds)
        except TokenizerUnavailable as exc:
            REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="error").inc()
            raise HTTPException(
                status_code=503,
                detail=_error(
                    "TOKENIZER_UNAVAILABLE", 503, str(exc), retriable=True
                ),
            ) from exc

        user_text = _last_user_text(body)
        try:
            scrub = await scrub_inbound(
                user_text, request_uuid, deps.scrub_engine, deps.tokenizer
            )
        except TokenizerUnavailable as exc:
            REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="error").inc()
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
                    prompt_uuid=prompt.uuid,
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
                    prompt_uuid=prompt.uuid,
                    outcome="redacted_and_quarantined",
                    payload={"category": sec.category},
                )
            )

        deps.state.put(
            request_uuid,
            RequestContext(
                user_claims=user,
                prompt=prompt,
                spiffe_id="",
                created_at=time.time(),
                jwt=token,
            ),
        )

        try:
            try:
                job_res = await deps.launcher.launch_and_wait(
                    request_uuid=request_uuid,
                    prompt_uuid=prompt.uuid,
                    litellm_url=deps.litellm_internal_url,
                    tokenized_user_input=scrub.scrubbed_text,
                )
            except AgentLaunchError as exc:
                REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="error").inc()
                raise HTTPException(
                    status_code=503,
                    detail=_error(
                        "AGENT_LAUNCH_FAILED", 503, str(exc), retriable=True
                    ),
                ) from exc
            except AgentTimeoutError as exc:
                REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="timeout").inc()
                raise HTTPException(
                    status_code=504,
                    detail=_error("AGENT_TIMEOUT", 504, str(exc), retriable=True),
                ) from exc
            except AgentFailedError as exc:
                REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="error").inc()
                raise HTTPException(
                    status_code=500,
                    detail=_error(
                        "AGENT_FAILED", 500, str(exc), retriable=True
                    ),
                ) from exc

            try:
                terminate = extract_terminate(prompt, job_res.terminate_body)
            except TerminateInvalid as exc:
                REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="error").inc()
                raise HTTPException(
                    status_code=500, detail=_error("AGENT_FAILED", 500, f"bad terminate: {exc}")
                ) from exc

            final = await _detokenize_response(
                terminate.body, request_uuid, deps.tokenizer
            )

            REQUESTS_TOTAL.labels(prompt=prompt.name, outcome="terminate").inc()
            REQUEST_DURATION.labels(prompt=prompt.name, outcome="terminate").observe(
                time.time() - start
            )
            await deps.audit.log(
                AuditEvent(
                    event_type="request",
                    request_uuid=request_uuid,
                    user_sub=user.sub,
                    prompt_uuid=prompt.uuid,
                    outcome="terminate",
                    payload={},
                )
            )
            import json as _json
            return {
                "id": request_uuid,
                "object": "chat.completion",
                "created": int(start),
                "model": prompt.name,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": _json.dumps(final)},
                    }
                ],
            }
        finally:
            try:
                await deps.tokenizer.release_request(request_uuid)
            finally:
                deps.state.drop(request_uuid)

    return router


def _last_user_text(body: dict[str, Any]) -> str:
    messages = body.get("messages", []) or []
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


async def _detokenize_response(
    obj: Any, request_uuid: str, tokenizer: TokenizerClient
) -> Any:
    from ag_gateway.mcp_proxy.routes import _replace_tokens_in_string

    if isinstance(obj, str):
        return await _replace_tokens_in_string(obj, request_uuid, tokenizer)
    if isinstance(obj, list):
        return [await _detokenize_response(x, request_uuid, tokenizer) for x in obj]
    if isinstance(obj, dict):
        return {k: await _detokenize_response(v, request_uuid, tokenizer) for k, v in obj.items()}
    return obj
