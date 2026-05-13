# Failure-modes runbook

| `error_type` | HTTP | Trigger | Immediate action | Root-cause checks |
|---|---|---|---|---|
| `JWT_VALIDATION_FAILED` | 401 | Bad signature / expired / wrong audience | **Page** on `reason=signature` spikes (active attack); ticket on `expired` | Check JWKS refresh metric; check clock skew |
| `JWT_MISSING` | 401 | No Authorization header | None | Likely a misconfigured client |
| `PROMPT_NOT_FOUND` | 404 | Unknown model name | None | Verify bundle includes the prompt |
| `PROMPT_VERIFY_FAILED` | 503 | Cosign verify failed at startup | **Page** | Inspect bundle signer + verify Rekor entry |
| `COST_CAP_EXCEEDED` | 429 | Per-prompt/user budget | None | Verify caps in prompt JSON |
| `SCRUB_FAILED` | 500 | Engine errored | Ticket → page on rate | Inspect logs; Presidio model OOM? |
| `TOKENIZER_UNAVAILABLE` | 503 | pii-tokenizer down | **Page** | Run pii-tokenizer's own runbook |
| `AGENT_LAUNCH_FAILED` | 503 | K8s Jobs API rejected | **Page** | K8s control plane health; quotas |
| `AGENT_TIMEOUT` | 504 | Job did not terminate in deadline | Ticket; page on rate | Inspect job logs; runaway-loop pattern? |
| `AGENT_FAILED` | 500 | Job exited non-zero or malformed terminate | Ticket; page on rate | Inspect job logs |
| `INTERNAL_ERROR` | 500 | Unhandled exception | **Page** | Stack trace in logs |

## Tool-result errors (returned to the agent, not the user)

| `error` | Trigger |
|---|---|
| `OPA_DENY` | User lacks permission(s) declared for `(mcp, tool)` |
| `SCHEMA_VALIDATION_FAILED` | Args don't match the MCP's request schema (or response failed validation) |
| `MCP_UNAVAILABLE` / `MCP_TIMEOUT` / `MCP_INTERNAL_ERROR` | Network or MCP-side failure |
| `MCP_BAD_RESPONSE` | MCP returned 4xx or non-JSON |
| `UUID_MISMATCH` | Tool call's `request_uuid` is missing/malformed/stale/foreign-spiffe — paging-class |
| `TOKENIZER_UNAVAILABLE` | pii-tokenizer down during detokenize |
| `SCRUB_FAILED` | Outbound scrub engine errored |

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
