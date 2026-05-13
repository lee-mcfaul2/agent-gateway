from __future__ import annotations

import json
from pathlib import Path

import pytest

from ag_gateway.schemas.scrub_categories import ScrubCatalog


def _bundle(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "schemas" / "shared"
    p.mkdir(parents=True)
    (p / "scrub-types.json").write_text(json.dumps(doc))
    return tmp_path


def test_load_categories(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path,
        {
            "categories": [
                {"name": "EMAIL", "severity": "pii", "patterns": [r"\S+@\S+\.\S+"]},
                {"name": "CODEWORD_PROJECT", "severity": "codeword", "patterns": [r"\bFalcon\b"]},
                {"name": "SECRET_API_KEY", "severity": "secret", "patterns": [r"sk-[A-Za-z0-9]+"]},
            ]
        },
    )
    cat = ScrubCatalog.from_bundle(root)
    assert "EMAIL" in cat.names()
    assert cat.get("SECRET_API_KEY").severity == "secret"
    assert cat.get("EMAIL").replacement_strategy == "tokenize"
    assert cat.get("CODEWORD_PROJECT").replacement_strategy == "redact"
    assert cat.get("SECRET_API_KEY").replacement_strategy == "redact"


def test_by_severity(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path,
        {
            "categories": [
                {"name": "EMAIL", "severity": "pii", "patterns": []},
                {"name": "SECRET_X", "severity": "secret", "patterns": []},
            ]
        },
    )
    cat = ScrubCatalog.from_bundle(root)
    secrets = cat.by_severity("secret")
    assert len(secrets) == 1
    assert secrets[0].name == "SECRET_X"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ScrubCatalog.from_bundle(tmp_path)
