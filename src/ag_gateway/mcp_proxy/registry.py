from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import MCP_STATE

log = get_logger(__name__)

MCPState = Literal["healthy", "degraded", "unknown"]


@dataclass(frozen=True)
class MCPEntry:
    name: str
    schema_version: str  # bundle_version — what version of the bundle this MCP was indexed from


class MCPRegistry:
    """Catalog of MCPs known to this gateway, derived from the v1.0 bundle manifest."""

    def __init__(self) -> None:
        self._by_name: dict[str, MCPEntry] = {}
        self._bundle_version: str = ""
        self._state: dict[str, MCPState] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_bundle(cls, bundle_root: Path) -> MCPRegistry:
        manifest = json.loads((bundle_root / "bundle-manifest.json").read_text())
        registry = cls()
        registry._bundle_version = str(manifest["bundle_version"])
        for svc in manifest.get("services", []):
            entry = MCPEntry(
                name=str(svc["mcp"]),
                schema_version=registry._bundle_version,
            )
            registry._by_name[entry.name] = entry
            registry._state[entry.name] = "unknown"
        log.info("mcp_registry.loaded", count=len(registry._by_name), version=registry._bundle_version)
        return registry

    def get(self, name: str) -> MCPEntry:
        return self._by_name[name]

    def names(self) -> list[str]:
        return sorted(self._by_name.keys())

    def state(self, name: str) -> MCPState:
        with self._lock:
            return self._state.get(name, "unknown")

    def set_state(self, name: str, state: MCPState) -> None:
        with self._lock:
            old = self._state.get(name)
            self._state[name] = state
            if old:
                MCP_STATE.labels(mcp=name, state=old).set(0)
            MCP_STATE.labels(mcp=name, state=state).set(1)
