# agent-gateway HTTP API

## Endpoints

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/chat/completions` | POST | OIDC JWT bearer | Run a prompt; returns the terminate response as an OpenAI-shaped completion |
| `/v1/mcp/<mcp>/<tool>` | POST | mesh mTLS (sandbox SPIFFE) | Tool-call endpoint for the agent container |
| `/healthz` | GET | none | Liveness |
| `/readyz` | GET | none | Readiness (tokenizer + OPA reachable) |
| `/metrics` | GET | mesh (Prometheus pull) | Prometheus exposition |

## /v1/chat/completions

Request:
```json
{
  "model": "support_chat_v1",
  "messages": [{"role": "user", "content": "free-form text from the user"}]
}
```

The `model` field is the **prompt name** (not an LLM provider model). It is mapped to a UUID via the loaded bundle. The user may not supply the prompt body — only reference it by name.

Response (success):
```json
{
  "id": "<request_uuid>",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "support_chat_v1",
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

See spec §9 for the full error-type catalog.

## /v1/mcp/<mcp>/<tool>

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
