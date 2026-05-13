from __future__ import annotations

import json
from pathlib import Path

import pytest

from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.schemas.scrub_categories import ScrubCatalog


@pytest.fixture
def catalog(tmp_path: Path) -> ScrubCatalog:
    p = tmp_path / "schemas" / "shared"
    p.mkdir(parents=True)
    (p / "scrub-types.json").write_text(
        json.dumps(
            {
                "categories": [
                    {"name": "EMAIL", "severity": "pii", "patterns": [r"\b\S+@\S+\.\S+\b"]},
                    {"name": "SECRET_API_KEY", "severity": "secret", "patterns": [r"sk-[A-Za-z0-9]+"]},
                    {"name": "CODEWORD_PROJECT", "severity": "codeword", "patterns": [r"\bFalcon\b"]},
                ]
            }
        )
    )
    return ScrubCatalog.from_bundle(tmp_path)


def test_regex_only_detects_secret(catalog: ScrubCatalog) -> None:
    class _Stub:
        def analyze(self, text: str, language: str = "en") -> list[object]:
            return []

    eng = ScrubEngine(catalog, presidio=_Stub())  # type: ignore[arg-type]
    dets = eng.scan("here is sk-ABC123 for you")
    cats = [d.category.name for d in dets]
    assert "SECRET_API_KEY" in cats


def test_codeword_detected(catalog: ScrubCatalog) -> None:
    class _Stub:
        def analyze(self, text: str, language: str = "en") -> list[object]:
            return []

    eng = ScrubEngine(catalog, presidio=_Stub())  # type: ignore[arg-type]
    dets = eng.scan("tell me about Falcon")
    assert any(d.category.name == "CODEWORD_PROJECT" for d in dets)


def test_overlap_secret_wins(catalog: ScrubCatalog) -> None:
    class _Stub:
        def analyze(self, text: str, language: str = "en") -> list[object]:
            return []

    eng = ScrubEngine(catalog, presidio=_Stub())  # type: ignore[arg-type]
    dets = eng.scan("token sk-emailx@x.com here")
    severities = {d.category.severity for d in dets}
    assert "secret" in severities


def test_email_regex_detected(catalog: ScrubCatalog) -> None:
    class _Stub:
        def analyze(self, text: str, language: str = "en") -> list[object]:
            return []

    eng = ScrubEngine(catalog, presidio=_Stub())  # type: ignore[arg-type]
    dets = eng.scan("mail me at alice@example.com please")
    assert any(d.category.name == "EMAIL" for d in dets)
