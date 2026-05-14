from __future__ import annotations

from ag_gateway.obs import metrics


def test_increment_and_render() -> None:
    metrics.REQUESTS_TOTAL.labels(prompt="support_chat", outcome="terminate").inc()
    metrics.TOKENS_GENERATED_TOTAL.labels(category="EMAIL").inc()
    text = metrics.render_text().decode()
    assert "gateway_requests_total" in text
    assert 'prompt="support_chat"' in text
    assert 'category="EMAIL"' in text


def test_uuid_mismatch_counter_present() -> None:
    metrics.UUID_MISMATCH_TOTAL.labels(reason="missing").inc()
    text = metrics.render_text().decode()
    assert "gateway_uuid_mismatch_total" in text
    assert 'reason="missing"' in text


def test_llm_guard_metrics_exist():
    from ag_gateway.obs.metrics import (
        LLM_GUARD_ENABLED,
        LLM_GUARD_DISABLED_TOTAL,
        LLM_GUARD_UNAVAILABLE_TOTAL,
        OUTBOUND_LLM_GUARD_BLOCKS_TOTAL,
    )
    assert LLM_GUARD_ENABLED is not None
    LLM_GUARD_DISABLED_TOTAL.labels(direction="inbound").inc()
    LLM_GUARD_UNAVAILABLE_TOTAL.labels(direction="outbound").inc()
    OUTBOUND_LLM_GUARD_BLOCKS_TOTAL.labels(mcp="kb", tool="search").inc()


def test_sandbox_finish_reason_metrics_exist():
    from ag_gateway.obs.metrics import (
        SANDBOX_FINISH_REASON_TOTAL,
        SANDBOX_RESPONSE_SCHEMA_MISMATCH_TOTAL,
    )
    SANDBOX_FINISH_REASON_TOTAL.labels(reason="terminate").inc()
    SANDBOX_RESPONSE_SCHEMA_MISMATCH_TOTAL.labels(mcp="kb", tool="search").inc()
