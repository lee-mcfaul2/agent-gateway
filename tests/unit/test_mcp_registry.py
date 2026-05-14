from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def bundle_v1(tmp_path: Path) -> Path:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / "bundle-manifest.json").write_text(json.dumps({
        "bundle_version": "1.0.0",
        "schema_library_version": "1.0.0",
        "build": {
            "timestamp": "2026-05-14T00:00:00Z",
            "source_commit": "abcdef0",
            "builder_id": "test",
        },
        "envelope_cost_caps": {
            "max_iterations": 8, "max_wallclock_ms": 300000, "max_cost_usd": 1.0
        },
        "services": [
            {
                "mcp": "kb",
                "tools": [
                    {
                        "name": "search",
                        "request_digest": "sha256:" + "a" * 64,
                        "response_digest": "sha256:" + "b" * 64,
                        "write": False,
                        "requires_permissions": ["kb:read"],
                    },
                    {
                        "name": "fetch",
                        "request_digest": "sha256:" + "c" * 64,
                        "response_digest": "sha256:" + "d" * 64,
                    },
                ],
            },
            {
                "mcp": "audit_db",
                "tools": [
                    {
                        "name": "search",
                        "request_digest": "sha256:" + "e" * 64,
                        "response_digest": "sha256:" + "f" * 64,
                    },
                ],
            },
        ],
    }))
    return bundle_root


def test_registry_loads_v1_services(bundle_v1: Path) -> None:
    from ag_gateway.mcp_proxy.registry import MCPRegistry
    reg = MCPRegistry.from_bundle(bundle_v1)
    kb = reg.get("kb")
    assert kb.name == "kb"
    assert kb.schema_version == "1.0.0"


def test_registry_unknown_mcp_raises(bundle_v1: Path) -> None:
    from ag_gateway.mcp_proxy.registry import MCPRegistry
    reg = MCPRegistry.from_bundle(bundle_v1)
    with pytest.raises(KeyError):
        reg.get("nope")


def test_registry_names_sorted(bundle_v1: Path) -> None:
    from ag_gateway.mcp_proxy.registry import MCPRegistry
    reg = MCPRegistry.from_bundle(bundle_v1)
    assert reg.names() == ["audit_db", "kb"]
