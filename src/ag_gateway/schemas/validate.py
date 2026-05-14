from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import referencing
import referencing.jsonschema as _rjs
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

    @lru_cache(maxsize=256)  # noqa: B019 — registry is a long-lived singleton
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


def validate_against(schema: dict[str, Any], payload: Any) -> str | None:
    """One-shot validation against an inline schema. Returns error message or None."""
    v = Draft202012Validator(schema)
    errors = sorted(v.iter_errors(payload), key=lambda e: list(e.absolute_path))
    return errors[0].message if errors else None


# ---------------------------------------------------------------------------
# Compiled-schema validator (used by BundleView and callers that need $ref
# resolution against a set of shared schemas).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SchemaValidator:
    """Thin wrapper around a compiled Draft202012Validator. Thread-safe; immutable."""

    _validator: Draft202012Validator

    def validate(self, instance: Any) -> str | None:
        """Return None on success, or a human-readable error string on failure."""
        errors = list(self._validator.iter_errors(instance))
        if not errors:
            return None
        return "; ".join(
            f"{list(e.path)}: {e.message}" if list(e.path) else e.message
            for e in errors
        )


def compile_schema(
    doc: dict[str, Any],
    shared_resources: dict[str, dict[str, Any]] | None = None,
) -> SchemaValidator:
    """Compile *doc* into a SchemaValidator, resolving $refs via *shared_resources*.

    *shared_resources* maps relative keys (e.g. ``"shared/uuid.json"``) to their
    parsed schema dicts.  Each dict must contain a ``$id`` URI that is the canonical
    reference target used by the schemas under compilation.
    """
    if shared_resources:
        resource_pairs = []
        for _key, schema_doc in shared_resources.items():
            id_ = schema_doc.get("$id")
            if id_:
                resource_pairs.append(
                    (
                        id_,
                        referencing.Resource.from_contents(
                            schema_doc,
                            default_specification=_rjs.DRAFT202012,
                        ),
                    )
                )
        registry = referencing.Registry().with_resources(resource_pairs)
        validator = Draft202012Validator(doc, registry=registry)
    else:
        validator = Draft202012Validator(doc)
    return SchemaValidator(_validator=validator)
