# Threat model

## What agent-gateway protects against

1. **Unauthenticated requests.** All ingress requires a valid OIDC JWT.
2. **User privilege escalation through the agent.** Per-tool-call OPA check uses the *user's* permissions, not the agent's. A compromised or prompt-injected agent cannot reach data the user lacks permission for.
3. **Plaintext PII at rest or in transit beyond the request edge.** Inbound PII is tokenized before reaching the agent, the LLM provider, audit logs, traces, or metrics. Plaintext exists only at the gateway during scrub + at the MCP-call boundary, never persisted.
4. **Credential exfiltration via prompts.** `SECRET_*` categories are detected, redacted with `[REDACTED]`, and the offending request is written to quarantine with the raw `sub` for forensic triage.
5. **Cross-request contamination.** Agent containers are one-shot K8s Jobs in the `sandbox` namespace; no state carries over.
6. **Replay / confused-deputy attacks.** Every tool call must parrot the `request_uuid` minted at ingress; SPIFFE check confirms the caller is the right container; OPA check confirms the user permits the action. Any layer's failure rejects + quarantines.
7. **Hostile MCP responses.** Outbound scrub runs on every MCP response; PII gets tokenized, secrets emit a paging-class `gateway_scrub_failures_total{direction=outbound}` metric.
8. **Prompt injection via tool results.** Every MCP result is wrapped in a `tool_result` envelope; the prompt's system message instructs the LLM to treat tool results as opaque data, not instructions.
9. **Cost-exhaustion attacks.** Per-prompt + per-user rolling-window cost cap; runaway loops also bounded by `cost_caps.max_iterations` in the prompt JSON.
10. **Schema drift / tampered MCPs.** Every MCP performs a digest handshake at gateway startup. Mismatch → MCP excluded + paging metric.

## What agent-gateway does NOT protect against

1. **A compromised IdP.** If the IdP's signing key is stolen, an attacker can mint valid JWTs. Defense is layered (KMS-backed keys, JWKS rotation, audit-log review).
2. **A compromised pii-tokenizer.** If `pii-tokenizer` is compromised during an active request, in-flight plaintext can be exfiltrated. Same residual risk as the tokenizer's own threat model.
3. **A compromised OPA bundle.** If an attacker swaps in a permissive policy bundle, calls that should be denied will allow. Defense: cosign-signed bundles + Rego test rules that catch the most catastrophic policy drift in CI.
4. **DoS at the network edge.** Rate limiting is per-IP in front of the gateway; LiteLLM's built-in rate limit is the per-user backstop. A determined adversary with botnets can still saturate.
5. **Side-channel attacks on the host.** Cache-timing, EM emanation, etc., are out of scope; the gateway assumes the K8s node is honest.
6. **Compromise of the K8s control plane.** A control-plane compromise can override RBAC and inject arbitrary pods. Defense is K8s's own layer (audit logs, OPA Gatekeeper for admission).

## Cryptographic primitives

- **JWT validation:** RS256 / ES256, with JWKS pulled from the IdP's well-known endpoint at startup and refreshed periodically.
- **mTLS:** provided by Linkerd between every in-cluster hop. SPIFFE identities issued by SPIRE.
- **Cosign verification:** sigstore keyless via Rekor + Fulcio, or static cosign public key for the prompt bundle + policy bundle.
- **Tokenization:** delegated to `pii-tokenizer` — AES-256-SIV-CMAC under per-request keys.

## Audit obligations

Every external request, every tool call, every paging-class verification failure produces an audit row in Postgres carrying: timestamp, request_uuid, user_sub, prompt_uuid, mcp, tool, outcome, payload (tokenized). Quarantine rows additionally carry the full snapshot of the conversation up to the failure point.

No plaintext PII ever appears in audit. SECRET-category events include the inbound text with the offending value redacted; surrounding context is preserved for triage.
