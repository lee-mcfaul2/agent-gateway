# Hook contracts

Each hook in `src/ag_gateway/hooks/` does one thing. This document is the contract you must respect when modifying or replacing one.

## auth_oidc

- Input: a raw JWT string
- Output: `UserClaims(sub, groups, permissions, raw)` or raises `JWTValidationError(reason, message)`
- Failure modes (each increments `gateway_jwt_failures_total{reason}`): signature, expired, audience, issuer, format, missing_claim
- Refresh: JWKS is refreshed every `GATEWAY_JWKS_REFRESH_SECONDS` (default 1h); failures increment `gateway_jwt_jwks_refresh_failures_total`

## scrub_inbound

- Input: user text, request_uuid, scrub engine, tokenizer client
- Output: `ScrubResult(scrubbed_text, secret_events)`
- PII categories tokenize via `pii-tokenizer` → metric `gateway_tokens_generated_total{category}`
- CODEWORD categories redact to `[REDACTED]` → metric `gateway_redactions_total{category}`
- SECRET categories redact to `[REDACTED]` → metric `gateway_secret_exfiltration_attempts_total{category}` + a `SecretEvent` is surfaced so the ingress layer can write to quarantine + audit

## scrub_outbound

- Same engine; the differences:
- SECRET hits emit `gateway_scrub_failures_total{direction=outbound}` (probable MCP compromise) and surface `OutboundSecretLeak` records
- Used by the MCP route after a successful MCP call returns

## opa_authz

- Coarse "can this user reach this MCP at all" reachability check. Per-tool
  authorization is enforced by each MCP under the hybrid authz model — the
  gateway forwards the user JWT in `Authorization: Bearer` on the outbound MCP
  call, and the MCP validates the JWT and runs its own per-tool permission check.
- Input: `(user_claims, mcp, request_uuid)`
- Output: `Decision(allow, reason)`
- Build the input doc using `build_input(...)` — keep field names stable; Rego policies depend on them

## envelope

- `wrap_success(payload, mcp, tool, request_uuid)` — for successful tool results
- `wrap_error(error, reason, mcp, tool, request_uuid)` — for any tool failure
- Both produce a `tool_result` body that the agent's loop driver knows to handle

## cost_cap

- In-memory rolling-window counter per `(prompt, user_sub)`
- `CostMeter.check(prompt, sub, CostCap(max_usd, window_seconds))` raises `CostCapExceeded` when the cap is hit
- LiteLLM's durable spend tracking remains the source of truth; ours is the fast pre-check

## tokenizer_client

- `init_request(uuid, ttl) -> InitResult`
- `tokenize(uuid, type, plaintext) -> token`
- `detokenize(uuid, token) -> (plaintext, type)`
- `release_request(uuid) -> None`
- All raise `TokenizerUnavailable` on transport failure or 5xx → ingress translates to `503 TOKENIZER_UNAVAILABLE`

## audit

- Async logger with bounded in-memory queue; drains to Postgres
- `AuditEvent(event_type, request_uuid, user_sub, prompt_uuid, mcp, tool, outcome, payload)`
- Queue full → `AuditWriteError` → ingress treats as 500
