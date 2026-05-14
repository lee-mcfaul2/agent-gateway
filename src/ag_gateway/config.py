from __future__ import annotations

from pydantic import Field, HttpUrl, PostgresDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Gateway runtime configuration, loaded from env vars."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # HTTP server
    listen_addr: str = Field(default=":8000")

    # OIDC
    oidc_issuer: HttpUrl
    oidc_audience: str
    jwks_refresh_seconds: int = 3600

    # External services
    tokenizer_url: HttpUrl
    opa_url: HttpUrl = HttpUrl("http://localhost:8181")

    # Bundle + prompts
    prompt_bundle_ref: str
    prompt_bundle_cosign_key: str

    # Audit + quarantine
    audit_database_url: PostgresDsn

    # Agent jobs
    agent_job_namespace: str = "sandbox"
    agent_job_timeout_seconds: int = 300
    agent_job_image: str

    # LiteLLM
    llm_providers_config: str = "/etc/gateway/litellm_config.yaml"
    litellm_internal_url: str = "http://localhost:4000"

    # Internal service URLs
    gateway_mcp_internal_url: str = "http://agent-gateway.gateway.svc.cluster.local:8080"

    # Telemetry
    log_level: str = "info"
    otel_exporter_otlp_endpoint: str | None = None
    service_name: str = "agent-gateway"

    # Quarantine
    quarantine_snapshot_max_bytes: int = 256 * 1024
    quarantine_retention_days: int = 90

    # LLM Guard — fail-closed: enabled by default; requires base_url when enabled
    llm_guard_enabled: bool = True
    llm_guard_base_url: str = ""
    llm_guard_timeout_seconds: float = 2.0

    # LLM routing
    default_model: str = "claude-sonnet-4-6"
    allowed_models: tuple[str, ...] = ("claude-sonnet-4-6", "claude-opus-4-7", "gpt-4o")

    @model_validator(mode="after")
    def _llm_guard_fail_closed(self) -> "Settings":
        if self.llm_guard_enabled and not self.llm_guard_base_url:
            raise ValueError(
                "LLM_GUARD config error: GATEWAY_LLM_GUARD_ENABLED=true requires "
                "GATEWAY_LLM_GUARD_BASE_URL to be set. Set base_url, or explicitly disable "
                "with GATEWAY_LLM_GUARD_ENABLED=false (dev only — security control disabled)."
            )
        return self


def load_settings() -> Settings:
    """Load and validate settings. Raises ValidationError on missing/bad config."""
    return Settings()  # type: ignore[call-arg]


class Config:
    """Thin wrapper around Settings exposing a from_env() classmethod.

    Raises ValueError (not ValidationError) on LLM Guard misconfiguration so
    callers can catch ValueError directly — consistent with the fail-closed
    contract documented in the task spec.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # --- proxy all Settings attributes ---
    def __getattr__(self, name: str) -> object:
        return getattr(self._settings, name)

    @classmethod
    def from_env(cls) -> "Config":
        """Load settings from the environment and return a Config instance.

        Raises ValueError if LLM Guard is enabled but no base URL is provided.
        """
        from pydantic import ValidationError

        try:
            s = Settings()  # type: ignore[call-arg]
        except ValidationError as exc:
            # Re-raise LLM Guard failures as plain ValueError so tests can
            # match on ValueError / "LLM_GUARD".  All other validation errors
            # propagate as ValidationError (same behaviour as load_settings).
            for err in exc.errors():
                if "LLM_GUARD" in str(err.get("msg", "")):
                    raise ValueError(str(err["msg"])) from exc
            raise
        return cls(s)
