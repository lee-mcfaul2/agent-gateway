from __future__ import annotations

import json
from pathlib import Path

import pytest

from ag_gateway.mcp_proxy.registry import MCPRegistry


def _bundle(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "mcps"
    p.mkdir(parents=True)
    (p / "catalog.json").write_text(json.dumps(doc))
    return tmp_path


def test_load_and_lookup(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path,
        {
            "mcps": [
                {
                    "name": "audit_db",
                    "spiffe": "spiffe://x/audit",
                    "schema_version": "v1",
                    "schema_digest": "sha256:1",
                    "requires_permissions": ["audit:read"],
                    "severity_class": "high",
                }
            ]
        },
    )
    reg = MCPRegistry.from_bundle(root)
    e = reg.get("audit_db")
    assert e.requires_permissions == ("audit:read",)
    assert reg.state("audit_db") == "unknown"


def test_set_state(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path,
        {"mcps": [{"name": "kb", "spiffe": "x", "schema_version": "v1", "schema_digest": "x"}]},
    )
    reg = MCPRegistry.from_bundle(root)
    reg.set_state("kb", "healthy")
    assert reg.state("kb") == "healthy"
    reg.set_state("kb", "degraded")
    assert reg.state("kb") == "degraded"


def test_missing_catalog(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        MCPRegistry.from_bundle(tmp_path)
