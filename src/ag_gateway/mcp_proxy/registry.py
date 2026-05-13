from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ag_gateway.obs.metrics import MCP_STATE

MCPState = Literal["healthy", "degraded", "unknown"]


@dataclass(frozen=True)
class MCPEntry:
    name: str
    spiffe: str
    schema_version: str
    schema_digest: str
    requires_permissions: tuple[str, ...] = ()
    severity_class: str = "normal"


class MCPRegistry:
    """Catalog of MCPs declared in the bundle. State (healthy/degraded) is mutable."""

    def __init__(self, entries: list[MCPEntry]) -> None:
        self._by_name: dict[str, MCPEntry] = {e.name: e for e in entries}
        self._state: dict[str, MCPState] = {e.name: "unknown" for e in entries}
        self._lock = threading.RLock()

    @classmethod
    def from_bundle(cls, bundle_root: Path) -> MCPRegistry:
        path = bundle_root / "mcps" / "catalog.json"
        if not path.exists():
            raise FileNotFoundError(f"mcp catalog not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        entries = [
            MCPEntry(
                name=str(e["name"]),
                spiffe=str(e["spiffe"]),
                schema_version=str(e["schema_version"]),
                schema_digest=str(e["schema_digest"]),
                requires_permissions=tuple(e.get("requires_permissions", ())),
                severity_class=str(e.get("severity_class", "normal")),
            )
            for e in doc.get("mcps", [])
        ]
        return cls(entries)

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
