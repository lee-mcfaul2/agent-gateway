from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()


# Response metrics
REQUESTS_TOTAL = Counter(
    "gateway_requests_total",
    "External requests received by the gateway, by outcome.",
    labelnames=("prompt", "outcome"),
    registry=REGISTRY,
)
REQUEST_DURATION = Histogram(
    "gateway_request_duration_seconds",
    "End-to-end external request latency.",
    labelnames=("prompt", "outcome"),
    registry=REGISTRY,
)
ITERATIONS_PER_REQUEST = Histogram(
    "gateway_iterations_per_request",
    "Agent loop iterations per external request.",
    labelnames=("prompt",),
    buckets=(1, 2, 3, 5, 8, 13, 21, 34, 55, 89),
    registry=REGISTRY,
)
TOOL_CALLS_TOTAL = Counter(
    "gateway_tool_calls_total",
    "MCP tool calls dispatched by the gateway, by outcome.",
    labelnames=("mcp", "tool", "outcome"),
    registry=REGISTRY,
)
TOKENS_GENERATED_TOTAL = Counter(
    "gateway_tokens_generated_total",
    "PII tokenize events by category.",
    labelnames=("category",),
    registry=REGISTRY,
)
REDACTIONS_TOTAL = Counter(
    "gateway_redactions_total",
    "Redact events by category.",
    labelnames=("category",),
    registry=REGISTRY,
)
LLM_COST_USD = Counter(
    "gateway_llm_cost_usd_total",
    "Cumulative LLM spend in USD, by prompt+provider+model.",
    labelnames=("prompt", "provider", "model"),
    registry=REGISTRY,
)
RESPONSE_BYTES = Histogram(
    "gateway_response_bytes",
    "Payload size in bytes.",
    labelnames=("prompt", "direction"),
    buckets=(64, 256, 1024, 4096, 16384, 65536, 262144, 1048576),
    registry=REGISTRY,
)

# Auth + authz failure metrics
JWT_FAILURES_TOTAL = Counter(
    "gateway_jwt_failures_total",
    "JWT validation failures by reason.",
    labelnames=("reason",),
    registry=REGISTRY,
)
JWT_JWKS_REFRESH_FAILURES_TOTAL = Counter(
    "gateway_jwt_jwks_refresh_failures_total",
    "JWKS refresh failures by reason.",
    labelnames=("reason",),
    registry=REGISTRY,
)
AUTHN_RATE_LIMIT_TOTAL = Counter(
    "gateway_authn_rate_limit_total",
    "Authn rate-limit triggers.",
    registry=REGISTRY,
)
OPA_DENIALS_TOTAL = Counter(
    "gateway_opa_denials_total",
    "OPA-denied tool calls.",
    labelnames=("mcp", "tool", "reason"),
    registry=REGISTRY,
)
COST_CAP_REJECTIONS_TOTAL = Counter(
    "gateway_cost_cap_rejections_total",
    "Cost cap rejections.",
    labelnames=("prompt",),
    registry=REGISTRY,
)

# Verification + security event metrics
OPA_ERRORS_TOTAL = Counter(
    "gateway_opa_errors_total",
    "OPA sidecar errors by reason.",
    labelnames=("reason",),
    registry=REGISTRY,
)
SCHEMA_FAILURES_TOTAL = Counter(
    "gateway_schema_failures_total",
    "Schema validation failures.",
    labelnames=("type", "reason", "mcp"),
    registry=REGISTRY,
)
SCRUB_FAILURES_TOTAL = Counter(
    "gateway_scrub_failures_total",
    "Scrub engine failures.",
    labelnames=("direction",),
    registry=REGISTRY,
)
DETOKENIZE_FAILURES_TOTAL = Counter(
    "gateway_detokenize_failures_total",
    "Detokenize failures.",
    labelnames=("reason",),
    registry=REGISTRY,
)
UUID_MISMATCH_TOTAL = Counter(
    "gateway_uuid_mismatch_total",
    "UUID parrot mismatch events.",
    labelnames=("reason",),
    registry=REGISTRY,
)
BUNDLE_VERIFY_FAILURES_TOTAL = Counter(
    "gateway_bundle_verify_failures_total",
    "Cosign / SLSA verify failures on the prompt bundle.",
    labelnames=("reason",),
    registry=REGISTRY,
)
SECRET_EXFIL_TOTAL = Counter(
    "gateway_secret_exfiltration_attempts_total",
    "User-supplied text containing SECRET_* categories.",
    labelnames=("category",),
    registry=REGISTRY,
)

# Schema-versioning + MCP state
SCHEMAS_SUPPORTED = Gauge(
    "gateway_schemas_supported",
    "Number of schema versions this gateway speaks.",
    labelnames=("version",),
    registry=REGISTRY,
)
SCHEMA_IN_USE = Gauge(
    "gateway_schema_in_use",
    "1 if traffic was seen for this schema version in the last 60s.",
    labelnames=("version",),
    registry=REGISTRY,
)
MCP_STATE = Gauge(
    "gateway_mcp_state",
    "MCP reachability state (1=present).",
    labelnames=("mcp", "state"),
    registry=REGISTRY,
)


def render_text() -> bytes:
    """Render the current registry in Prometheus exposition format."""
    return generate_latest(REGISTRY)
