from __future__ import annotations

import json
from pathlib import Path

import pytest

from ag_gateway.prompts.registry import PromptNotFound, PromptRegistry


def _write(dir: Path, name: str, body: dict) -> None:
    (dir / f"{name}.json").write_text(json.dumps(body))


def test_load_and_lookup(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    _write(
        tmp_path / "prompts",
        "support_chat",
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "support_chat_v1",
            "services": [{"name": "kb", "spiffe": "spiffe://x", "schema_digest": "sha256:1"}],
            "allowed_responses": {"oneOf": []},
            "cost_caps": {"max_iterations": 10},
        },
    )
    reg = PromptRegistry.from_bundle(tmp_path)
    p = reg.by_name("support_chat_v1")
    assert p.uuid == "11111111-1111-1111-1111-111111111111"
    assert p.services[0]["name"] == "kb"
    assert p.cost_caps["max_iterations"] == 10
    assert reg.by_uuid(p.uuid).name == p.name


def test_lookup_missing_raises(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    reg = PromptRegistry.from_bundle(tmp_path)
    with pytest.raises(PromptNotFound):
        reg.by_name("nope")


def test_duplicate_name_rejected(tmp_path: Path) -> None:
    d = tmp_path / "prompts"
    d.mkdir()
    body = {"id": "11111111-1111-1111-1111-111111111111", "name": "x"}
    _write(d, "a", body)
    body2 = {"id": "22222222-2222-2222-2222-222222222222", "name": "x"}
    _write(d, "b", body2)
    with pytest.raises(ValueError):
        PromptRegistry.from_bundle(tmp_path)


def test_missing_prompts_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        PromptRegistry.from_bundle(tmp_path)
