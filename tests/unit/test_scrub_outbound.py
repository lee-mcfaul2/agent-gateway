from __future__ import annotations

import json
from pathlib import Path

import pytest

from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.scrub_outbound import REDACTION_MARKER, scrub_outbound
from ag_gateway.schemas.scrub_categories import ScrubCatalog


class _StubPresidio:
    def analyze(self, text: str, language: str = "en") -> list[object]:
        return []


class _FakeTokenizer:
    async def tokenize(self, request_uuid: str, type_: str, plaintext: str) -> str:
        return f"TOKEN_{type_}_OUT"


@pytest.fixture
def engine(tmp_path: Path) -> ScrubEngine:
    p = tmp_path / "schemas" / "shared"
    p.mkdir(parents=True)
    (p / "scrub-types.json").write_text(
        json.dumps(
            {
                "categories": [
                    {"name": "EMAIL", "severity": "pii", "patterns": [r"\b\S+@\S+\.\S+\b"]},
                    {"name": "SECRET_API_KEY", "severity": "secret", "patterns": [r"sk-[A-Za-z0-9]+"]},
                ]
            }
        )
    )
    return ScrubEngine(ScrubCatalog.from_bundle(tmp_path), presidio=_StubPresidio())  # type: ignore[arg-type]


async def test_pii_tokenized_on_outbound(engine: ScrubEngine) -> None:
    res = await scrub_outbound("returned bob@x.com", "req", engine, _FakeTokenizer())  # type: ignore[arg-type]
    assert "TOKEN_EMAIL_OUT" in res.scrubbed_text
    assert res.leaks == []


async def test_secret_leak_recorded(engine: ScrubEngine) -> None:
    res = await scrub_outbound(
        "leaked sk-XYZ987 from mcp", "req", engine, _FakeTokenizer()  # type: ignore[arg-type]
    )
    assert REDACTION_MARKER in res.scrubbed_text
    assert len(res.leaks) == 1
    assert res.leaks[0].category == "SECRET_API_KEY"
