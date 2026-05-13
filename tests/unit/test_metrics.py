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
