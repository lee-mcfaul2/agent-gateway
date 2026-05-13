from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.schemas.scrub_categories import ScrubCatalog


class _Stub:
    def analyze(self, text: str, language: str = "en") -> list[object]:
        return []


@pytest.fixture
def engine(tmp_path: Path) -> ScrubEngine:
    p = tmp_path / "schemas" / "shared"
    p.mkdir(parents=True)
    (p / "scrub-types.json").write_text(
        json.dumps(
            {"categories": [{"name": "SECRET_X", "severity": "secret", "patterns": [r"sk-[A-Z0-9]+"]}]}
        )
    )
    return ScrubEngine(ScrubCatalog.from_bundle(tmp_path), presidio=_Stub())  # type: ignore[arg-type]


@given(prefix=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=50))
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_secret_always_detected_regardless_of_context(prefix: str, engine: ScrubEngine) -> None:
    needle = "sk-ABCDEF"
    text = prefix + " " + needle + " trailing"
    dets = engine.scan(text)
    cats = [d.category.name for d in dets]
    assert "SECRET_X" in cats
