# agent-gateway HTTP API

## Endpoints

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/chat/completions` | POST | OIDC JWT bearer | Run a prompt; returns the terminate response as an OpenAI-shaped completion |
| `/v1/bundle_digest` | GET | mesh mTLS (sandbox SPIFFE) | Returns current bundle digest; sandboxes verify on startup |
| `/v1/mcp/<mcp>/<tool>` | POST | mesh mTLS (sandbox SPIFFE) | Tool-call endpoint for the agent container |
| `/healthz` | GET | none | Liveness |
| `/readyz` | GET | none | Readiness (tokenizer + OPA reachable) |
| `/metrics` | GET | mesh (Prometheus pull) | Prometheus exposition |

## POST /v1/chat/completions

Inbound user request. Body must validate against the bundled `user-prompt.json` schema:

```json
{
  "schema_uuid": "<UUID identifying the user-prompt schema>",
  "prompt_uuid": "<UUID minted by the caller, audit/trace join key>",
  "text": "<the user's raw prompt>",
  "model": "<optional model hint, must be in allowed_models>"
}
```

Headers: `Authorization: Bearer <jwt>` (required), `traceparent: <W3C trace>` (optional).

The gateway:
1. Validates the JWT (OIDC)
2. Validates the body against the bundled `user-prompt.json`
3. Runs the inbound LLM Guard scan (fail-closed)
4. Scrubs PII + tokenizes via pii-tokenizer (existing flow)
5. Computes `AVAILABLE_TOOLS` from JWT permissions × bundle tool catalog
6. Resolves the model (request.model if in allowed_models, else config default)
7. Launches a sandbox Job with the resolved env set (request_uuid, prompt_uuid, model, available_tools, etc.)
8. Returns an OpenAI-shape chat-completion with the agent's terminate.response in `choices[0].message.content`

Response (success):
```json
{
  "id": "<request_uuid>",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "claude-sonnet-4-6",
  "choices": [{
    "index": 0,
    "finish_reason": "stop",
    "message": {"role": "assistant", "content": "<terminate-payload-as-json-string>"}
  }]
}
```

Error envelope (4xx/5xx):
```json
{
  "error_type": "JWT_VALIDATION_FAILED",
  "retriable": false,
  "message": "JWT signature did not verify"
}
```

See `docs/failure-modes.md` for the full error-type catalog.

## GET /v1/bundle_digest

Returns the gateway's current bundle digest. Sandbox containers call this at startup
to verify their embedded bundle matches the gateway's. Mismatch aborts the sandbox
before any LLM call.

Response:
```json
{"digest": "sha256:..."}
```

## POST /v1/mcp/\<mcp\>/\<tool\>

Called by the agent container with:
```json
{
  "request_uuid": "<the uuid the gateway minted on init>",
  "args": { "...": "..." }
}
```

Response:
```json
{
  "tool_result": {
    "ok": true,
    "mcp": "kb",
    "tool": "search",
    "request_uuid": "...",
    "data": {"...": "..."}
  }
}
```

Or on failure:
```json
{
  "tool_result": {
    "ok": false,
    "error": "OPA_DENY",
    "reason": "missing_permission:audit:read",
    "request_uuid": "..."
  }
}
```

The agent is expected to interpret a failed `tool_result` and continue / terminate gracefully.
