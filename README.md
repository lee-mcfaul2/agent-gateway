# agent-gateway

Security and policy plane for the AI Agent Security Platform. LiteLLM Proxy deployment with custom hooks for OIDC JWT auth, Presidio + regex scrubbing, OPA per-MCP authorization, pii-tokenizer integration, and a one-shot agent-job launcher.

Spec: `ai-security/docs/superpowers/specs/2026-05-12-agent-gateway-design.md` in the umbrella workspace.

## Quickstart

```
make install     # uv sync
make test        # pytest tests/unit
make run-local   # docker compose up --build
```

## Layout

- `src/ag_gateway/` — gateway extension package (hooks, prompts, jobs, mcp_proxy, schemas, obs)
- `policy/` — OPA Rego policy bundle
- `litellm_config.yaml` — LiteLLM model list + virtual-key settings
- `tools/compile-policy/` — operator CLI for signing/publishing the policy bundle
- `deploy/` — Dockerfile + dev compose + Helm chart fragment
- `tests/` — unit, integration, conformance, e2e
- `docs/` — api, hooks, policy, failure-modes, threat-model

## License

Apache 2.0.
