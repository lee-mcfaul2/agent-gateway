# Failure-modes runbook

| `error_type` | HTTP | Trigger | Immediate action | Root-cause checks |
|---|---|---|---|---|
| `JWT_VALIDATION_FAILED` | 401 | Bad signature / expired / wrong audience | **Page** on `reason=signature` spikes (active attack); ticket on `expired` | Check JWKS refresh metric; check clock skew |
| `JWT_MISSING` | 401 | No Authorization header | None | Likely a misconfigured client |
| `USER_PROMPT_INVALID` | 400 | Request body fails `user-prompt.json` schema | None | Verify client is sending the v1.0 request shape |
| `MODEL_NOT_ALLOWED` | 400 | `model` field not in configured allowlist | None | Check `models.allowed_models` in Helm values |
| `PROMPT_BLOCKED_BY_LLM_GUARD` | 400 | LLM Guard returned `block` on inbound text | None | Review flagged prompt in audit log |
| `LLM_GUARD_UNAVAILABLE` | 503 | LLM Guard configured but unreachable (retriable) | **Page** | Check LLM Guard pod health; gateway is fail-closed |
| `PROMPT_VERIFY_FAILED` | 503 | Cosign verify failed at startup | **Page** | Inspect bundle signer + verify Rekor entry |
| `COST_CAP_EXCEEDED` | 429 | Per-prompt/user budget | None | Verify caps in prompt JSON |
| `SCRUB_FAILED` | 500 | Engine errored | Ticket → page on rate | Inspect logs; Presidio model OOM? |
| `TOKENIZER_UNAVAILABLE` | 503 | pii-tokenizer down | **Page** | Run pii-tokenizer's own runbook |
| `AGENT_LAUNCH_FAILED` | 503 | K8s Jobs API rejected | **Page** | K8s control plane health; quotas |
| `AGENT_TIMEOUT` | 504 | Job did not terminate in deadline | Ticket; page on rate | Inspect job logs; runaway-loop pattern? |
| `AGENT_FAILED` | 500 | Job exited non-zero or malformed terminate | Ticket; page on rate | Inspect job logs |
| `SANDBOX_SCHEMA_MISMATCH` | 500 | Sandbox aborted on response-schema mismatch | **Page** | Bundle version skew? Check bundle digest endpoint |
| `LITELLM_UPSTREAM_ERROR` | 502 | LLM call failed inside sandbox | Ticket; page on rate | Check LLM provider status; inspect sandbox logs |
| `SANDBOX_INTERNAL_ERROR` | 500 | Sandbox aborted due to internal error | Ticket; page on rate | Inspect sandbox Job logs |
| `INTERNAL_ERROR` | 500 | Unhandled exception | **Page** | Stack trace in logs |

## Tool-result errors (returned to the agent, not the user)

| `error` | Trigger |
|---|---|
| `OPA_DENY` | User lacks the minimum permission required to reach `mcp` (coarse reachability — per-tool authz enforced at the MCP) |
| `SCHEMA_VALIDATION_FAILED` | Args don't match the MCP's request schema (or response failed validation) |
| `MCP_UNAVAILABLE` / `MCP_TIMEOUT` / `MCP_INTERNAL_ERROR` | Network or MCP-side failure |
| `MCP_BAD_RESPONSE` | MCP returned 4xx or non-JSON |
| `UUID_MISMATCH` | Tool call's `request_uuid` is missing/malformed/stale/foreign-spiffe — paging-class |
| `TOKENIZER_UNAVAILABLE` | pii-tokenizer down during detokenize |
| `SCRUB_FAILED` | Outbound scrub engine errored |
| `OUTBOUND_LLM_GUARD_UNAVAILABLE` | LLM Guard unreachable while scanning an MCP response (retriable) |
| `OUTBOUND_BLOCKED` | LLM Guard blocked the MCP response (data exfiltration / injection attempt) |

## Alert: LLMGuardDisabled (page)

Fires when `gateway_llm_guard_enabled == 0` for 1 minute. This means a gateway pod
has `llm_guard.enabled=false` in its config — only expected during local dev. In
production, this is a security regression: agent prompts are flowing without
prompt-injection scanning. Investigate immediately.

Likely causes:
- A pod restarted with stale config from a development branch
- An operator manually set `enabled=false` and forgot to revert
- The LLM Guard service was experiencing prolonged downtime and someone disabled
  the scan as a workaround

Resolution: flip `llm_guard.enabled=true` in the Helm values and re-roll the gateway.

## Generic ops checklist

1. `kubectl get pods -n gateway -l app=agent-gateway` — all replicas healthy?
2. `kubectl logs -n gateway deploy/agent-gateway --tail=200` — recent errors?
3. `kubectl exec -n gateway deploy/agent-gateway -c opa -- curl -s localhost:8181/health`
4. Prometheus: `gateway_requests_total{outcome!="terminate"}` rate
5. Prometheus: `gateway_uuid_mismatch_total` rate (spikes = active probing)
6. Prometheus: `gateway_secret_exfiltration_attempts_total` rate
7. Quarantine: `SELECT * FROM quarantine WHERE ts > now() - interval '1 hour' ORDER BY ts DESC;`

## Restart-only mitigation

Gateway pods hold per-request state (the JWT → UUID map). Restarting a pod drops any in-flight requests it was serving (those return errors to their callers, who retry). Other replicas continue. K8s scheduling brings the replica back; the new pod re-runs the bundle handshake on startup.
