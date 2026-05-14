from __future__ import annotations

import pytest
import respx
from httpx import Response

from ag_gateway.hooks.llm_guard import LLMGuardClient, LLMGuardUnavailable, ScanResult


@respx.mock
async def test_scan_inbound_allow():
    respx.post("http://llm-guard/scan").mock(
        return_value=Response(200, json={"action": "allow", "categories": [], "spans": []})
    )
    client = LLMGuardClient(base_url="http://llm-guard", timeout_seconds=2.0, enabled=True)
    result = await client.scan_inbound("hello", "req-1")
    assert isinstance(result, ScanResult)
    assert result.action == "allow"


@respx.mock
async def test_scan_inbound_block():
    respx.post("http://llm-guard/scan").mock(
        return_value=Response(
            200, json={"action": "block", "categories": ["prompt_injection"], "spans": []}
        )
    )
    client = LLMGuardClient(base_url="http://llm-guard", timeout_seconds=2.0, enabled=True)
    result = await client.scan_inbound("malicious", "req-1")
    assert result.action == "block"
    assert "prompt_injection" in result.categories


@respx.mock
async def test_scan_inbound_unavailable_raises():
    respx.post("http://llm-guard/scan").mock(return_value=Response(503))
    client = LLMGuardClient(base_url="http://llm-guard", timeout_seconds=2.0, enabled=True)
    with pytest.raises(LLMGuardUnavailable):
        await client.scan_inbound("x", "req-1")


async def test_disabled_returns_allow():
    client = LLMGuardClient(base_url="", timeout_seconds=2.0, enabled=False)
    result = await client.scan_inbound("anything", "req-1")
    assert result.action == "allow"


def test_enabled_without_url_raises_at_init():
    with pytest.raises(ValueError):
        LLMGuardClient(base_url="", timeout_seconds=2.0, enabled=True)


@respx.mock
async def test_outbound_scan():
    respx.post("http://llm-guard/scan").mock(
        return_value=Response(200, json={"action": "flag", "categories": ["pii"], "spans": []})
    )
    client = LLMGuardClient(base_url="http://llm-guard", timeout_seconds=2.0, enabled=True)
    result = await client.scan_outbound_mcp_response("response text", "req-1", "kb", "search")
    assert result.action == "flag"
