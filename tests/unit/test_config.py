from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from ag_gateway.config import Settings, load_settings

REQUIRED_ENV = {
    "GATEWAY_OIDC_ISSUER": "https://idp.example.com",
    "GATEWAY_OIDC_AUDIENCE": "ag-gateway",
    "GATEWAY_TOKENIZER_URL": "https://pii-tokenizer.platform.svc.cluster.local:8443",
    "GATEWAY_PROMPT_BUNDLE_REF": "ghcr.io/example/prompts:v1",
    "GATEWAY_PROMPT_BUNDLE_COSIGN_KEY": "/etc/cosign.pub",
    "GATEWAY_AUDIT_DATABASE_URL": "postgresql://u:p@db/audit",
    "GATEWAY_AGENT_JOB_IMAGE": "ghcr.io/example/sandbox:v1",
    # LLM Guard is enabled by default (fail-closed); base URL is required when enabled.
    "GATEWAY_LLM_GUARD_BASE_URL": "http://llm-guard.platform.svc.cluster.local:8080",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os.environ):
        if k.startswith("GATEWAY_"):
            monkeypatch.delenv(k, raising=False)


def test_load_settings_with_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    s = load_settings()
    assert s.listen_addr == ":8000"
    assert s.agent_job_namespace == "sandbox"
    assert str(s.tokenizer_url).startswith("https://")


def test_load_settings_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_settings_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GATEWAY_LISTEN_ADDR", ":9000")
    monkeypatch.setenv("GATEWAY_AGENT_JOB_TIMEOUT_SECONDS", "600")
    s = load_settings()
    assert s.listen_addr == ":9000"
    assert s.agent_job_timeout_seconds == 600


def test_llm_guard_enabled_true_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GATEWAY_LLM_GUARD_BASE_URL", raising=False)
    monkeypatch.setenv("GATEWAY_LLM_GUARD_ENABLED", "true")
    from ag_gateway.config import Config
    with pytest.raises(ValueError, match="LLM_GUARD"):
        Config.from_env()


def test_llm_guard_disabled_allows_empty_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GATEWAY_LLM_GUARD_ENABLED", "false")
    monkeypatch.delenv("GATEWAY_LLM_GUARD_BASE_URL", raising=False)
    from ag_gateway.config import Config
    cfg = Config.from_env()
    assert cfg.llm_guard_enabled is False
    assert cfg.llm_guard_base_url == ""


def test_llm_guard_enabled_with_url_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GATEWAY_LLM_GUARD_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_LLM_GUARD_BASE_URL", "http://llm-guard.platform.svc.cluster.local:8080")
    from ag_gateway.config import Config
    cfg = Config.from_env()
    assert cfg.llm_guard_enabled is True
    assert cfg.llm_guard_base_url.startswith("http://")


def test_default_model_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    # LLM Guard must be disabled or have a URL; disable it for this test
    monkeypatch.setenv("GATEWAY_LLM_GUARD_ENABLED", "false")
    from ag_gateway.config import Config
    cfg = Config.from_env()
    assert cfg.default_model != ""
    assert isinstance(cfg.allowed_models, tuple)
    assert len(cfg.allowed_models) >= 1
