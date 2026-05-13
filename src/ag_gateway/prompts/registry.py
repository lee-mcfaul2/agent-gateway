from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ag_gateway.obs.logging import get_logger


log = get_logger(__name__)


@dataclass(frozen=True)
class Prompt:
    """An immutable prompt artifact."""

    uuid: str
    name: str
    body: dict[str, Any] = field(repr=False)

    @property
    def services(self) -> list[dict[str, Any]]:
        return list(self.body.get("services", []))

    @property
    def allowed_responses(self) -> dict[str, Any]:
        return dict(self.body.get("allowed_responses", {}))

    @property
    def cost_caps(self) -> dict[str, Any]:
        return dict(self.body.get("cost_caps", {}))


class PromptNotFound(KeyError):
    pass


class PromptRegistry:
    """In-memory registry; loaded once from a bundle, then read-only."""

    def __init__(self) -> None:
        self._by_name: dict[str, Prompt] = {}
        self._by_uuid: dict[str, Prompt] = {}

    @classmethod
    def from_bundle(cls, bundle_root: Path) -> "PromptRegistry":
        registry = cls()
        prompts_dir = bundle_root / "prompts"
        if not prompts_dir.exists():
            raise FileNotFoundError(f"prompts dir not found in bundle: {prompts_dir}")

        for path in sorted(prompts_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as f:
                body = json.load(f)
            uuid = str(body["id"])
            name = str(body.get("name", path.stem))
            prompt = Prompt(uuid=uuid, name=name, body=body)
            if name in registry._by_name:
                raise ValueError(f"duplicate prompt name: {name}")
            if uuid in registry._by_uuid:
                raise ValueError(f"duplicate prompt uuid: {uuid}")
            registry._by_name[name] = prompt
            registry._by_uuid[uuid] = prompt

        log.info("prompts.loaded", count=len(registry._by_name))
        return registry

    def by_name(self, name: str) -> Prompt:
        try:
            return self._by_name[name]
        except KeyError as e:
            raise PromptNotFound(name) from e

    def by_uuid(self, uuid: str) -> Prompt:
        try:
            return self._by_uuid[uuid]
        except KeyError as e:
            raise PromptNotFound(uuid) from e

    def names(self) -> list[str]:
        return sorted(self._by_name.keys())
