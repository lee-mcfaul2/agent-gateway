from __future__ import annotations

from pydantic import Field, HttpUrl, PostgresDsn
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

    # Telemetry
    log_level: str = "info"
    otel_exporter_otlp_endpoint: str | None = None
    service_name: str = "agent-gateway"

    # Quarantine
    quarantine_snapshot_max_bytes: int = 256 * 1024
    quarantine_retention_days: int = 90


def load_settings() -> Settings:
    """Load and validate settings. Raises ValidationError on missing/bad config."""
    return Settings()  # type: ignore[call-arg]
