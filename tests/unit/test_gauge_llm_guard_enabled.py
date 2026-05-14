"""Verify the gateway_llm_guard_enabled gauge behaves correctly. Prod alerts
key on this gauge transitioning to 0, so the set/get behavior is load-bearing."""
from __future__ import annotations

from ag_gateway.obs.metrics import LLM_GUARD_ENABLED


def test_gauge_set_to_1_when_enabled():
    LLM_GUARD_ENABLED.set(1)
    assert LLM_GUARD_ENABLED._value.get() == 1.0


def test_gauge_set_to_0_when_disabled():
    LLM_GUARD_ENABLED.set(0)
    assert LLM_GUARD_ENABLED._value.get() == 0.0


def test_gauge_toggling():
    LLM_GUARD_ENABLED.set(1)
    assert LLM_GUARD_ENABLED._value.get() == 1.0
    LLM_GUARD_ENABLED.set(0)
    assert LLM_GUARD_ENABLED._value.get() == 0.0
    LLM_GUARD_ENABLED.set(1)
    assert LLM_GUARD_ENABLED._value.get() == 1.0
