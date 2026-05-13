from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ag_gateway.obs.metrics import SCHEMA_FAILURES_TOTAL


@dataclass(frozen=True)
class SchemaError:
    schema_ref: str
    reason: str
    path: str


class SchemaRegistry:
    """Loads schemas under bundle_root/schemas/ and validates payloads against them."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @lru_cache(maxsize=256)
    def _load(self, schema_ref: str) -> Draft202012Validator:
        path = self._root / "schemas" / schema_ref
        if not path.exists():
            raise FileNotFoundError(f"schema not found: {schema_ref}")
        with path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        return Draft202012Validator(schema)

    def validate(
        self, payload: Any, schema_ref: str, *, kind: str = "request", mcp: str = ""
    ) -> SchemaError | None:
        """Returns None on success, SchemaError on failure (and emits metric)."""
        try:
            validator = self._load(schema_ref)
        except FileNotFoundError:
            SCHEMA_FAILURES_TOTAL.labels(type=kind, reason="missing_schema", mcp=mcp).inc()
            return SchemaError(schema_ref, "schema not found", "")
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
        if not errors:
            return None
        first = errors[0]
        SCHEMA_FAILURES_TOTAL.labels(type=kind, reason="validation", mcp=mcp).inc()
        return SchemaError(
            schema_ref=schema_ref,
            reason=first.message,
            path="/".join(str(p) for p in first.absolute_path),
        )


def validate_against(schema: dict, payload: Any) -> str | None:
    """One-shot validation against an inline schema. Returns error message or None."""
    v = Draft202012Validator(schema)
    errors = sorted(v.iter_errors(payload), key=lambda e: list(e.absolute_path))
    return errors[0].message if errors else None
