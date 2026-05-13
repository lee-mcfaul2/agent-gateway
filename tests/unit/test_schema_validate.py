from __future__ import annotations

import json
from pathlib import Path

from ag_gateway.schemas.validate import SchemaRegistry, validate_against


def _write_schema(root: Path, rel: str, schema: dict) -> None:
    path = root / "schemas" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema))


def test_validate_ok(tmp_path: Path) -> None:
    _write_schema(
        tmp_path,
        "audit_db/v1/search.request.json",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    reg = SchemaRegistry(tmp_path)
    assert reg.validate({"query": "x"}, "audit_db/v1/search.request.json") is None


def test_validate_fail(tmp_path: Path) -> None:
    _write_schema(
        tmp_path,
        "audit_db/v1/search.request.json",
        {"type": "object", "required": ["query"]},
    )
    reg = SchemaRegistry(tmp_path)
    err = reg.validate({}, "audit_db/v1/search.request.json", mcp="audit_db")
    assert err is not None
    assert "query" in err.reason


def test_missing_schema(tmp_path: Path) -> None:
    reg = SchemaRegistry(tmp_path)
    err = reg.validate({}, "nope/v1/x.json")
    assert err is not None
    assert err.reason == "schema not found"


def test_validate_against_inline() -> None:
    schema = {"type": "object", "required": ["a"]}
    assert validate_against(schema, {"a": 1}) is None
    msg = validate_against(schema, {})
    assert msg is not None and "a" in msg
